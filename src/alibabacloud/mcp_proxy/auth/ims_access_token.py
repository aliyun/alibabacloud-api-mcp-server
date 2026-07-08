from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.exceptions import CredentialException
from alibabacloud_openapi_util.client import Client as OpenApiUtilClient
from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_tea_openapi.exceptions import ClientException as OpenApiClientException
from alibabacloud_tea_openapi.utils_models import Config, OpenApiRequest, Params
from darabonba.runtime import RuntimeOptions

DEFAULT_IMS_CLIENT_ID = "4071151845732613353"
DEFAULT_IMS_SCOPE = "/internal/acs/openapi"
DEFAULT_IMS_ENDPOINT = "ramoauth.aliyuncs.com"

IMS_ACTION = "GenerateAccessToken"
IMS_VERSION = "2026-04-21"

_LOGGER = logging.getLogger(__name__)

# Keys whose string values are replaced in INFO logs (full JWT still available at DEBUG).
_REDACT_EXACT_KEYS = frozenset(
    {
        "AccessToken",
        "access_token",
        "accessToken",
        "IdToken",
        "id_token",
        "SecurityToken",
        "security_token",
        "RefreshToken",
        "refresh_token",
    }
)

_credential_singleton: CredentialClient | None = None


def _redact_sensitive_for_log(obj: Any, depth: int = 0) -> Any:
    if depth > 24:
        return "<max depth>"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in _REDACT_EXACT_KEYS and isinstance(v, str) and v.strip():
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact_sensitive_for_log(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_redact_sensitive_for_log(x, depth + 1) for x in obj]
    return obj


def _response_to_json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _log_ims_generate_access_token_response(response: Any) -> None:
    """Log tea ``call_api_async`` return value: INFO = redacted, DEBUG = full raw JSON."""
    try:
        _LOGGER.info(
            "IMS GenerateAccessToken response (tokens redacted): %s",
            _response_to_json_text(_redact_sensitive_for_log(response)),
        )
    except (TypeError, ValueError) as exc:
        _LOGGER.info(
            "IMS GenerateAccessToken response (serialize failed: %s): %r",
            exc,
            response,
        )
    try:
        _LOGGER.debug(
            "IMS GenerateAccessToken debug response (tokens redacted): %s",
            _response_to_json_text(_redact_sensitive_for_log(response)),
        )
    except (TypeError, ValueError):
        _LOGGER.debug(
            "IMS GenerateAccessToken debug response could not be serialized safely."
        )


def get_default_credential_client() -> CredentialClient:
    """Return a process-wide CredentialClient using the default credential chain."""
    global _credential_singleton
    if _credential_singleton is None:
        _credential_singleton = CredentialClient()
    return _credential_singleton


def parse_ims_generate_access_token_body(body: Any) -> tuple[str, datetime | None]:
    """
    Extract access token and optional expiry from IMS GenerateAccessToken JSON body.

    Accepts dict or JSON string; field names may be PascalCase or snake_case.
    Successful RPC responses often nest fields under ``Data`` (see IMS API).
    """
    from alibabacloud.mcp_proxy.auth.token_provider import TokenAcquisitionError

    if body is None:
        raise TokenAcquisitionError("IMS GenerateAccessToken returned an empty body.")

    if isinstance(body, str):
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TokenAcquisitionError("IMS response body is not valid JSON.") from exc
    elif isinstance(body, dict):
        data = body
    elif isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                try:
                    return parse_ims_generate_access_token_body(item)
                except TokenAcquisitionError:
                    continue
        raise TokenAcquisitionError("IMS response body list did not include an access token.")
    else:
        raise TokenAcquisitionError("IMS response body has an unexpected type.")

    token = _find_access_token(data)
    if not token:
        token = _deep_find_access_token_value(data) or ""

    if not token:
        code = _first_str(data, "Code", "code")
        message = _first_str(data, "Message", "message")
        if message or code:
            raise TokenAcquisitionError(
                f"IMS GenerateAccessToken failed: code={code or 'unknown'}, message={message or 'n/a'}"
            )
        raise TokenAcquisitionError(
            "IMS GenerateAccessToken response did not include an access token."
        )

    expires_at = _parse_expiry_from_nested(data)
    if expires_at is None:
        expires_at = _deep_find_expires_value(data)
    return token, expires_at


def _ims_payload_dicts(root: dict[str, Any]) -> list[dict[str, Any]]:
    """IMS may return token fields at the root or under ``Data`` / ``data``."""
    ordered: list[dict[str, Any]] = [root]
    for key in ("Data", "data"):
        nested = root.get(key)
        if isinstance(nested, dict):
            ordered.append(nested)
    return ordered


def _find_access_token(data: dict[str, Any]) -> str:
    for payload in _ims_payload_dicts(data):
        raw = _first_str(payload, "AccessToken", "access_token", "Token", "token")
        if raw:
            return raw.strip()
    return ""


def _parse_expiry_from_nested(root: dict[str, Any]) -> datetime | None:
    for payload in _ims_payload_dicts(root):
        expires_at = _parse_expiry_from_single_dict(payload)
        if expires_at is not None:
            return expires_at
    return None


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _deep_find_access_token_value(obj: Any, *, depth: int = 0, max_depth: int = 16) -> str | None:
    """Depth-first search for common IMS / OAuth token field names."""
    if depth > max_depth or obj is None:
        return None
    if isinstance(obj, dict):
        for key in (
            "AccessToken",
            "access_token",
            "accessToken",
            "IdToken",
            "id_token",
            "JwtToken",
            "jwt_token",
        ):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for key in ("Token", "token"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip() and len(val.strip()) >= 16:
                return val.strip()
        for v in obj.values():
            found = _deep_find_access_token_value(v, depth=depth + 1, max_depth=max_depth)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find_access_token_value(item, depth=depth + 1, max_depth=max_depth)
            if found:
                return found
    return None


def _deep_find_expires_value(obj: Any, *, depth: int = 0, max_depth: int = 16) -> datetime | None:
    if depth > max_depth or obj is None:
        return None
    if isinstance(obj, dict):
        exp = _parse_expiry_from_single_dict(obj)
        if exp is not None:
            return exp
        for v in obj.values():
            found = _deep_find_expires_value(v, depth=depth + 1, max_depth=max_depth)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find_expires_value(item, depth=depth + 1, max_depth=max_depth)
            if found is not None:
                return found
    return None


def extract_token_from_ims_api_response(response: Any) -> tuple[str, datetime | None]:
    """
    Parse token from the dict returned by tea OpenAPI ``call_api_async`` (body + headers + statusCode).

    Tries ``response['body']`` first, then shallow parse of the full response, then deep search.
    """
    from alibabacloud.mcp_proxy.auth.token_provider import TokenAcquisitionError

    if not isinstance(response, dict):
        raise TokenAcquisitionError(
            f"IMS GenerateAccessToken returned unexpected type: {type(response).__name__}"
        )

    body = response.get("body")
    candidates: list[Any] = []
    if body is not None:
        candidates.append(body)
    candidates.append(response)

    last: TokenAcquisitionError | None = None
    for raw in candidates:
        try:
            return parse_ims_generate_access_token_body(raw)
        except TokenAcquisitionError as exc:
            last = exc
            continue

    token = _deep_find_access_token_value(response)
    if token:
        _LOGGER.debug("IMS access token resolved via deep search on API response.")
        expires_at = _deep_find_expires_value(response)
        return token, expires_at

    status = response.get("statusCode")
    body_preview = repr(body)[:400] if body is not None else "None"
    raise TokenAcquisitionError(
        "IMS GenerateAccessToken response did not include an access token. "
        f"statusCode={status!r}, last_error={last}, body_preview={body_preview}"
    )


def _parse_expiry_from_single_dict(data: dict[str, Any]) -> datetime | None:
    expire_raw = _first_str(
        data,
        "ExpireTime",
        "expire_time",
        "Expiration",
        "expiration",
        "ExpiresAt",
        "expires_at",
    )
    if expire_raw:
        normalized = expire_raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone(UTC)
        except ValueError:
            pass

    expires_in = data.get("ExpiresIn") or data.get("expires_in")
    if expires_in is None:
        return None
    try:
        seconds = int(float(str(expires_in).strip()))
    except (TypeError, ValueError):
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


async def generate_access_token_async(
    *,
    client_id: str,
    scope: str,
    endpoint: str = DEFAULT_IMS_ENDPOINT,
    credential_client: CredentialClient | None = None,
):
    """
    Call IMS GenerateAccessToken using the given (or default) credential client.

    Uses RPC signing (signature algorithm v2) as required by alibabacloud-tea-openapi.
    """
    from alibabacloud.mcp_proxy.auth.token_provider import BearerToken, TokenAcquisitionError

    cred = credential_client or get_default_credential_client()
    try:
        loaded_credential = cred.get_credential()
    except CredentialException as exc:
        raise TokenAcquisitionError(
            "Could not load Alibaba Cloud credentials from the default chain. "
            "Configure environment variables, ~/.aliyun/config.json, or instance role. "
            f"Details: {exc}"
        ) from exc
    provider_name = getattr(loaded_credential, "provider_name", None) or "unknown"
    _LOGGER.debug(
        "Using Alibaba Cloud credential provider for IMS token acquisition: %s",
        provider_name,
    )

    config = Config(credential=cred, signature_algorithm="v2")
    config.endpoint = endpoint
    client = OpenApiClient(config)

    params = Params(
        action=IMS_ACTION,
        version=IMS_VERSION,
        protocol="HTTPS",
        method="POST",
        auth_type="AK",
        style="RPC",
        pathname="/",
        req_body_type="json",
        body_type="json",
    )
    queries = OpenApiUtilClient.query(
        {
            "ClientId": client_id,
            "Scope": scope,
        }
    )
    request = OpenApiRequest(query=queries)
    runtime = RuntimeOptions()

    try:
        response = await client.call_api_async(params, request, runtime)
    except OpenApiClientException as exc:
        detail = exc.message or exc.code or str(exc)
        raise TokenAcquisitionError(f"IMS GenerateAccessToken failed: {detail}") from exc
    except Exception as exc:
        raise TokenAcquisitionError(f"IMS GenerateAccessToken failed: {exc}") from exc

    _log_ims_generate_access_token_response(response)

    token_value, expires_at = extract_token_from_ims_api_response(response)
    if expires_at is not None:
        _LOGGER.debug("IMS Bearer token acquired; expires_at=%s", expires_at.isoformat())
    else:
        _LOGGER.debug("IMS Bearer token acquired without an expiry timestamp.")
    return BearerToken(value=token_value, expires_at=expires_at)


class ImsBearerTokenSource:
    """Bearer token source that exchanges default-chain credentials for an IMS access token."""

    def __init__(
        self,
        *,
        client_id: str,
        scope: str,
        endpoint: str = DEFAULT_IMS_ENDPOINT,
        credential_client: CredentialClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._scope = scope
        self._endpoint = endpoint
        self._credential_client = credential_client

    async def fetch_token(self):
        return await generate_access_token_async(
            client_id=self._client_id,
            scope=self._scope,
            endpoint=self._endpoint,
            credential_client=self._credential_client,
        )
