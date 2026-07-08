from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import environ

UTC = timezone.utc
from typing import Protocol

import anyio
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_credentials.utils import auth_constant as credential_types

from alibabacloud.mcp_proxy.auth.ims_access_token import ImsBearerTokenSource
from alibabacloud.mcp_proxy.config import TokenSettings

LOGGER = logging.getLogger(__name__)


class TokenAcquisitionError(RuntimeError):
    """Raised when the proxy cannot obtain a bearer token."""


@dataclass(slots=True, frozen=True)
class BearerToken:
    value: str
    expires_at: datetime | None = None

    def is_expiring_within(self, seconds: int) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) + timedelta(seconds=seconds) >= self.expires_at


class BearerTokenSource(Protocol):
    async def fetch_token(self) -> BearerToken:
        """Return a bearer token for the upstream MCP server."""


class StaticBearerTokenSource:
    def __init__(self, token: str) -> None:
        self._token = token

    async def fetch_token(self) -> BearerToken:
        return BearerToken(value=self._token)


class CommandBearerTokenSource:
    """Fetch a bearer token by executing a local command."""

    def __init__(self, command: str) -> None:
        self._command = command

    async def fetch_token(self) -> BearerToken:
        completed = await anyio.to_thread.run_sync(self._run)
        stdout = completed.stdout.strip()
        if not stdout:
            raise TokenAcquisitionError("Token command completed without output.")

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return BearerToken(value=stdout)

        access_token = str(payload.get("access_token") or payload.get("token") or "").strip()
        if not access_token:
            raise TokenAcquisitionError(
                "Token command JSON output must include access_token or token."
            )

        expires_at = _parse_expiry(payload)
        return BearerToken(value=access_token, expires_at=expires_at)

    def _run(self) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            self._command,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise TokenAcquisitionError(
                f"Token command failed with exit code {completed.returncode}: {stderr}"
            )
        return completed


class CachedBearerTokenProvider:
    def __init__(self, source: BearerTokenSource, *, refresh_skew_seconds: int = 60) -> None:
        self._source = source
        self._refresh_skew_seconds = refresh_skew_seconds
        self._cached_token: BearerToken | None = None
        self._lock = anyio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            if not force_refresh and self._cached_token is not None:
                if not self._cached_token.is_expiring_within(self._refresh_skew_seconds):
                    return self._cached_token.value

            self._cached_token = await self._source.fetch_token()
            return self._cached_token.value


def _build_explicit_static_credential_client_from_env() -> CredentialClient | None:
    access_key_id = (environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID") or "").strip()
    access_key_secret = (environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or "").strip()
    security_token = (environ.get("ALIBABA_CLOUD_SECURITY_TOKEN") or "").strip()

    if not access_key_id and not access_key_secret and not security_token:
        return None

    if not access_key_id:
        raise TokenAcquisitionError(
            "ALIBABA_CLOUD_ACCESS_KEY_ID is required when configuring static Alibaba Cloud credentials."
        )
    if not access_key_secret:
        raise TokenAcquisitionError(
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET is required when configuring static Alibaba Cloud credentials."
        )

    if security_token:
        LOGGER.debug("Using explicit static STS credential from environment.")
        return CredentialClient(
            CredentialConfig(
                type=credential_types.STS,
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                security_token=security_token,
            )
        )

    LOGGER.debug("Using explicit static AK credential from environment.")
    return CredentialClient(
        CredentialConfig(
            type=credential_types.ACCESS_KEY,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
    )


def build_token_provider(settings: TokenSettings) -> CachedBearerTokenProvider:
    if settings.bearer_token:
        source: BearerTokenSource = StaticBearerTokenSource(settings.bearer_token)
    elif settings.token_command:
        source = CommandBearerTokenSource(settings.token_command)
    else:
        source = ImsBearerTokenSource(
            client_id=settings.ims_client_id,
            scope=settings.ims_scope,
            endpoint=settings.ims_endpoint,
            credential_client=_build_explicit_static_credential_client_from_env(),
        )

    return CachedBearerTokenProvider(source, refresh_skew_seconds=settings.refresh_skew_seconds)


def _parse_expiry(payload: dict[str, object]) -> datetime | None:
    expires_at_raw = payload.get("expires_at")
    if isinstance(expires_at_raw, str) and expires_at_raw.strip():
        normalized = expires_at_raw.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)

    expires_in_raw = payload.get("expires_in")
    if expires_in_raw is None:
        return None

    try:
        seconds = int(expires_in_raw)
    except (TypeError, ValueError) as exc:
        raise TokenAcquisitionError("expires_in must be an integer number of seconds.") from exc

    return datetime.now(UTC) + timedelta(seconds=seconds)
