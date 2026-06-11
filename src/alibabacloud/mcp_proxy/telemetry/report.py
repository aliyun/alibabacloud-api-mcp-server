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
import json
import logging
import os
import time
import urllib.error
import urllib.request
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
LOCAL_REPORT_URL_ENV = "ALIBABACLOUD_TELEMETRY_REPORT_URL"
ENDPOINT_ENV = "ALIBABACLOUD_TELEMETRY_ENDPOINT"

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


def _endpoint() -> str:
    """Return OpenAPI endpoint host, optionally overridden for pre-release."""
    raw = os.environ.get(ENDPOINT_ENV, "").strip()
    if not raw:
        return ENDPOINT
    endpoint = raw
    for prefix in ("https://", "http://"):
        if endpoint.startswith(prefix):
            endpoint = endpoint[len(prefix):]
            break
    endpoint = endpoint.split("/", 1)[0].strip()
    return endpoint or ENDPOINT


def _create_client() -> OpenApiClient:
    """Build an OpenAPI client using the default Alibaba Cloud credential chain."""
    credential = CredentialClient()
    config = Config(
        credential=credential,
        endpoint=_endpoint(),
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


def _local_report_url() -> str | None:
    url = os.environ.get(LOCAL_REPORT_URL_ENV)
    if url and url.strip():
        return url.strip()
    return None


def _parse_response_body(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _post_local_report(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    timeout_s = max(READ_TIMEOUT_MS, CONNECT_TIMEOUT_MS) / 1000
    try:
        # The URL is an explicit developer override for local testing.
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return {
                "statusCode": response.getcode(),
                "headers": dict(response.headers.items()),
                "body": _parse_response_body(response.read()),
            }
    except urllib.error.HTTPError as exc:
        return {
            "statusCode": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": _parse_response_body(exc.read()),
        }


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
            Optional: ``endTimestamp``, ``mcpTool``, ``cliCommand``,
            ``eventTag``, ``skillName``, ``toolRequestId``, ``errorMessage``,
            ``pluginName``, ``mcpSessionId`` and token counters.
            Set ``ALIBABACLOUD_TELEMETRY_ENDPOINT`` to override the signed
            OpenAPI endpoint, for example the pre-release endpoint. Set
            ``ALIBABACLOUD_TELEMETRY_REPORT_URL`` only to POST directly to a
            local/dev report endpoint instead of using OpenAPI signing.
            Required-field validation is enforced server-side.

    Returns:
        The raw response dict (``{statusCode, headers, body}``) on success.
        ``None`` if the request fails after ``MAX_ATTEMPTS`` attempts.
    """
    if not _validate_payload(payload):
        return None

    local_url = _local_report_url()
    client = None if local_url else _get_client()
    params = None if local_url else _build_params()
    request = None if local_url else _build_request(payload)
    runtime = None if local_url else _build_runtime()

    last_failure: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = (
                _post_local_report(local_url, payload)
                if local_url
                else client.call_api(params, request, runtime)
            )
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

    local_url = _local_report_url()
    client = None if local_url else _get_client()
    params = None if local_url else _build_params()
    request = None if local_url else _build_request(payload)
    runtime = None if local_url else _build_runtime()

    last_failure: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = (
                await asyncio.to_thread(_post_local_report, local_url, payload)
                if local_url
                else await client.call_api_async(params, request, runtime)
            )
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
