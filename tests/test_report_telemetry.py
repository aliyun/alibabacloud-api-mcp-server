from __future__ import annotations

from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from alibabacloud.mcp_proxy.telemetry import report as report_mod
from alibabacloud.mcp_proxy.telemetry import report_telemetry, report_telemetry_async


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(report_mod, "_RETRY_BACKOFF_S", (0, 0, 0))
    monkeypatch.delenv(report_mod.LOCAL_REPORT_URL_ENV, raising=False)
    monkeypatch.delenv(report_mod.ENDPOINT_ENV, raising=False)
    report_mod._client_singleton = None


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(report_mod, "_get_client", lambda: client)
    return client


def test_endpoint_defaults_to_production(monkeypatch) -> None:
    monkeypatch.delenv(report_mod.ENDPOINT_ENV, raising=False)
    assert report_mod._endpoint() == report_mod.ENDPOINT


def test_endpoint_can_be_overridden_for_pre(monkeypatch) -> None:
    monkeypatch.setenv(
        report_mod.ENDPOINT_ENV,
        "https://openapi-mcp-pre.cn-hangzhou.aliyuncs.com/reportTelemetry",
    )
    assert report_mod._endpoint() == "openapi-mcp-pre.cn-hangzhou.aliyuncs.com"



def test_sync_returns_response_on_success(mock_client) -> None:
    mock_client.call_api.return_value = {"statusCode": 200, "body": {"success": True, "requestId": "r1"}}
    result = report_telemetry({"clientName": "cli", "eventType": "tool_call"})
    assert result is not None
    assert result["statusCode"] == 200
    assert mock_client.call_api.call_count == 1


def test_sync_retries_on_non_200_then_succeeds(mock_client) -> None:
    mock_client.call_api.side_effect = [
        {"statusCode": 500, "body": {"success": False}},
        {"statusCode": 200, "body": {"success": True}},
    ]
    result = report_telemetry({"clientName": "cli"})
    assert result is not None
    assert result["statusCode"] == 200
    assert mock_client.call_api.call_count == 2


def test_sync_retries_on_exception_then_succeeds(mock_client) -> None:
    mock_client.call_api.side_effect = [
        TimeoutError("connect timed out"),
        {"statusCode": 200, "body": {"success": True}},
    ]
    result = report_telemetry({"clientName": "cli"})
    assert result is not None
    assert mock_client.call_api.call_count == 2


def test_sync_uses_local_report_url_when_env_is_set(monkeypatch, mock_client) -> None:
    calls = []

    def fake_post(url, payload):
        calls.append((url, payload))
        return {"statusCode": 200, "body": {"success": True, "requestId": "local-r1"}}

    monkeypatch.setenv(report_mod.LOCAL_REPORT_URL_ENV, "http://localhost:8080/reportTelemetry")
    monkeypatch.setattr(report_mod, "_post_local_report", fake_post)

    payload = {"clientName": "cli", "eventType": "mcp_tool_use"}
    result = report_telemetry(payload)

    assert result == {"statusCode": 200, "body": {"success": True, "requestId": "local-r1"}}
    assert calls == [("http://localhost:8080/reportTelemetry", payload)]
    mock_client.call_api.assert_not_called()


def test_local_report_http_error_keeps_response_body(monkeypatch) -> None:
    class FakeHeaders:
        def items(self):
            return [("Content-Type", "application/json")]

    class FakeHttpError(urllib.error.HTTPError):
        def read(self):
            return b'{"success":false,"message":"missing required field: sessionId"}'

    def fake_urlopen(*_args, **_kwargs):
        raise FakeHttpError(
            "http://localhost:7001/reportTelemetry",
            400,
            "Bad Request",
            FakeHeaders(),
            None,
        )

    monkeypatch.setattr(report_mod.urllib.request, "urlopen", fake_urlopen)

    result = report_mod._post_local_report(
        "http://localhost:7001/reportTelemetry",
        {"clientName": "cli"},
    )

    assert result == {
        "statusCode": 400,
        "headers": {"Content-Type": "application/json"},
        "body": {"success": False, "message": "missing required field: sessionId"},
    }


def test_sync_returns_none_after_max_attempts(mock_client) -> None:
    mock_client.call_api.side_effect = TimeoutError("nope")
    result = report_telemetry({"clientName": "cli"})
    assert result is None
    assert mock_client.call_api.call_count == report_mod.MAX_ATTEMPTS


def test_sync_rejects_non_dict_payload(mock_client) -> None:
    assert report_telemetry("not a dict") is None  # type: ignore[arg-type]
    assert report_telemetry(None) is None  # type: ignore[arg-type]
    mock_client.call_api.assert_not_called()


def test_sync_swallows_unexpected_exceptions(mock_client) -> None:
    mock_client.call_api.side_effect = RuntimeError("boom")
    # Must not raise - telemetry is fire-and-forget.
    assert report_telemetry({"clientName": "cli"}) is None


async def test_async_returns_response_on_success(mock_client) -> None:
    async def fake_call(*_args, **_kwargs):
        return {"statusCode": 200, "body": {"success": True}}

    mock_client.call_api_async.side_effect = fake_call
    result = await report_telemetry_async({"clientName": "cli"})
    assert result is not None
    assert result["statusCode"] == 200


async def test_async_uses_local_report_url_when_env_is_set(monkeypatch, mock_client) -> None:
    calls = []

    def fake_post(url, payload):
        calls.append((url, payload))
        return {"statusCode": 200, "body": {"success": True, "requestId": "local-r2"}}

    monkeypatch.setenv(report_mod.LOCAL_REPORT_URL_ENV, "http://localhost:8080/reportTelemetry")
    monkeypatch.setattr(report_mod, "_post_local_report", fake_post)

    payload = {"clientName": "cli", "eventType": "llm_call"}
    result = await report_telemetry_async(payload)

    assert result == {"statusCode": 200, "body": {"success": True, "requestId": "local-r2"}}
    assert calls == [("http://localhost:8080/reportTelemetry", payload)]
    mock_client.call_api_async.assert_not_called()


async def test_async_retries_then_gives_up(mock_client) -> None:
    async def fake_call(*_args, **_kwargs):
        raise TimeoutError("nope")

    mock_client.call_api_async.side_effect = fake_call
    result = await report_telemetry_async({"clientName": "cli"})
    assert result is None
    assert mock_client.call_api_async.call_count == report_mod.MAX_ATTEMPTS


def test_params_are_roa_post_with_correct_pathname() -> None:
    params = report_mod._build_params()
    assert params.style == "ROA"
    assert params.method == "POST"
    assert params.pathname == "/reportTelemetry"
    assert params.action == "ReportTelemetry"
    assert params.version == "2024-11-30"


def test_runtime_uses_3s_timeouts() -> None:
    runtime = report_mod._build_runtime()
    assert runtime.connect_timeout == 3000
    assert runtime.read_timeout == 3000
