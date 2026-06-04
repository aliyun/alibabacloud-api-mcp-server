"""
Report telemetry to the Alibaba Cloud OpenAPI backend service.

Backend OpenAPI:
    Endpoint:  openapi-agent-toolkits.aliyuncs.com
    Version:   2024-11-30
    Action:    ReportTelemetry  (ROA, POST /reportTelemetry, JSON body)

This module is intentionally fire-and-forget: failures are retried up to
``MAX_ATTEMPTS`` times and then logged. Callers receive the raw response on
success or ``None`` on definitive failure - exceptions are never propagated
to avoid telemetry disrupting the host application.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_tea_openapi.exceptions import ClientException as OpenApiClientException
from alibabacloud_tea_openapi.utils_models import Config, OpenApiRequest, Params
from darabonba.runtime import RuntimeOptions

ENDPOINT = "openapi-agent-toolkits.aliyuncs.com"
API_VERSION = "2024-11-30"
ACTION = "ReportTelemetry"
PATHNAME = "/reportTelemetry"

USER_AGENT = "AlibabaCloud-MCP-Proxy/telemetry"

# Connect/read timeouts in milliseconds. Capped at 3s per the backend SLA to
# avoid stalling the caller and back-pressuring the proxy under failure.
CONNECT_TIMEOUT_MS = 3000
READ_TIMEOUT_MS = 3000

# Total attempts performed before giving up. The user spec asks for 3 retries
# on failure -> initial attempt + 3 retries = 4 attempts.
MAX_ATTEMPTS = 4

# Backoff (seconds) applied BEFORE each retry attempt, indexed by retry number
# (0 = before 1st retry). Kept short so worst-case latency stays bounded.
_RETRY_BACKOFF_S = (0.1, 0.3, 0.5)

_LOGGER = logging.getLogger(__name__)
_client_singleton: OpenApiClient | None = None


def _create_client() -> OpenApiClient:
    """Build an OpenAPI client using the default Alibaba Cloud credential chain."""
    credential = CredentialClient()
    config = Config(
        credential=credential,
        endpoint=ENDPOINT,
        user_agent=USER_AGENT,
    )
    return OpenApiClient(config)


def _get_client() -> OpenApiClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = _create_client()
    return _client_singleton


def _build_params() -> Params:
    return Params(
        action=ACTION,
        version=API_VERSION,
        protocol="HTTPS",
        method="POST",
        auth_type="AK",
        style="ROA",
        pathname=PATHNAME,
        req_body_type="json",
        body_type="json",
    )


def _build_request(payload: dict[str, Any]) -> OpenApiRequest:
    return OpenApiRequest(body=payload)


def _build_runtime() -> RuntimeOptions:
    runtime = RuntimeOptions()
    runtime.connect_timeout = CONNECT_TIMEOUT_MS
    runtime.read_timeout = READ_TIMEOUT_MS
    return runtime


def _validate_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        _LOGGER.warning(
            "ReportTelemetry skipped: payload must be a dict, got %s",
            type(payload).__name__,
        )
        return False
    return True


def _evaluate_response(response: Any) -> tuple[bool, str | None]:
    """Return (is_success, failure_reason)."""
    if not isinstance(response, dict):
        return False, f"unexpected response type {type(response).__name__}"
    status = response.get("statusCode")
    if status == 200:
        return True, None
    body_preview = repr(response.get("body"))[:300]
    return False, f"non-200 status {status!r}; body={body_preview}"


def _describe_exception(exc: Exception) -> str:
    if isinstance(exc, OpenApiClientException):
        return f"OpenAPI[{exc.code or 'n/a'}] {exc.message or exc}"
    return f"{type(exc).__name__}: {exc}"


def report_telemetry(payload: dict[str, Any]) -> dict | None:
    """
    Synchronously POST a telemetry payload to the backend OpenAPI service.

    Args:
        payload: Telemetry fields as defined in the backend schema.
            Required: ``clientName``, ``eventType``, ``startTimestamp``,
            ``toolName``, ``sessionId``, ``status``.
            Optional: ``endTimestamp``, ``turn`` (int32), ``mcpTool``,
            ``cliCommand``, ``querySummary``, ``skillName``, ``toolRequestId``,
            ``errorMessage``, ``pluginName``.
            Required-field validation is enforced server-side.

    Returns:
        The raw response dict (``{statusCode, headers, body}``) on success.
        ``None`` if the request fails after ``MAX_ATTEMPTS`` attempts.
    """
    if not _validate_payload(payload):
        return None

    client = _get_client()
    params = _build_params()
    request = _build_request(payload)
    runtime = _build_runtime()

    last_failure: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.call_api(params, request, runtime)
            ok, reason = _evaluate_response(response)
            if ok:
                return response
            last_failure = reason
            _LOGGER.warning(
                "ReportTelemetry attempt %d/%d failed: %s",
                attempt, MAX_ATTEMPTS, reason,
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must never raise
            last_failure = _describe_exception(exc)
            _LOGGER.warning(
                "ReportTelemetry attempt %d/%d raised: %s",
                attempt, MAX_ATTEMPTS, last_failure,
            )

        if attempt < MAX_ATTEMPTS:
            backoff = _RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)]
            time.sleep(backoff)

    _LOGGER.error(
        "ReportTelemetry exhausted %d attempts. Last failure: %s",
        MAX_ATTEMPTS, last_failure,
    )
    return None


async def report_telemetry_async(payload: dict[str, Any]) -> dict | None:
    """Async variant of :func:`report_telemetry`. Same contract, never raises."""
    if not _validate_payload(payload):
        return None

    client = _get_client()
    params = _build_params()
    request = _build_request(payload)
    runtime = _build_runtime()

    last_failure: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.call_api_async(params, request, runtime)
            ok, reason = _evaluate_response(response)
            if ok:
                return response
            last_failure = reason
            _LOGGER.warning(
                "ReportTelemetry attempt %d/%d failed: %s",
                attempt, MAX_ATTEMPTS, reason,
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must never raise
            last_failure = _describe_exception(exc)
            _LOGGER.warning(
                "ReportTelemetry attempt %d/%d raised: %s",
                attempt, MAX_ATTEMPTS, last_failure,
            )

        if attempt < MAX_ATTEMPTS:
            backoff = _RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)]
            await asyncio.sleep(backoff)

    _LOGGER.error(
        "ReportTelemetry exhausted %d attempts. Last failure: %s",
        MAX_ATTEMPTS, last_failure,
    )
    return None
