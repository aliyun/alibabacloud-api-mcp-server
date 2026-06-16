from __future__ import annotations

from unittest.mock import patch

import pytest

from alibabacloud.mcp_proxy.cli import _build_telemetry_payload, build_parser, main


_REQUIRED_ARGS = [
    "plugin-telemetry",
    "--client-name", "claude-code",
    "--event-type", "skill_invocation",
    "--start-timestamp", "2026-05-08T10:30:00Z",
    "--tool-name", "describe_instances",
    "--session-id", "sess-abc",
    "--status", "success",
]


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


# ── argparse routing & field mapping ──────────────────────────────────────

def test_required_only_builds_minimal_payload() -> None:
    args = _parse(_REQUIRED_ARGS)
    payload = _build_telemetry_payload(args)
    assert payload == {
        "clientName": "claude-code",
        "eventType": "skill_invocation",
        "startTimestamp": "2026-05-08T10:30:00Z",
        "toolName": "describe_instances",
        "sessionId": "sess-abc",
        "status": "success",
    }


def test_optional_fields_forwarded_with_camel_keys() -> None:
    args = _parse([
        *_REQUIRED_ARGS,
        "--end-timestamp", "2026-05-08T10:31:00Z",
        "--mcp-tool", "ecs.describe",
        "--cli-command", "aliyun ecs DescribeInstances",
        "--event-tag", "list ecs",
        "--skill-name", "azure-prepare",
        "--tool-request-id", "req-1",
        "--error-message", "",
        "--plugin-name", "alibabacloud",
        "--span-id", "span-001",
        "--parent-span-id", "span-000",
    ])
    payload = _build_telemetry_payload(args)
    assert payload["endTimestamp"] == "2026-05-08T10:31:00Z"
    assert "turn" not in payload  # turn embedded in toolName, not a separate field
    assert payload["mcpTool"] == "ecs.describe"
    assert payload["cliCommand"] == "aliyun ecs DescribeInstances"
    assert payload["eventTag"] == "list ecs"
    assert payload["skillName"] == "azure-prepare"
    assert payload["toolRequestId"] == "req-1"
    assert payload["pluginName"] == "alibabacloud"
    assert "spanId" not in payload  # span ids kept local-only
    assert "parentSpanId" not in payload
    assert "errorMessage" not in payload  # empty optional dropped


def test_timestamp_alias_maps_to_start_timestamp() -> None:
    # Replace --start-timestamp with the Azure-style alias --timestamp.
    argv = [
        "plugin-telemetry",
        "--client-name", "claude-code",
        "--event-type", "skill_invocation",
        "--timestamp", "2026-05-08T10:30:00Z",
        "--tool-name", "describe_instances",
        "--session-id", "sess-abc",
        "--status", "success",
    ]
    args = _parse(argv)
    payload = _build_telemetry_payload(args)
    assert payload["startTimestamp"] == "2026-05-08T10:30:00Z"



def test_missing_required_field_exits_nonzero(capsys) -> None:
    argv = [a for a in _REQUIRED_ARGS if a != "--client-name"]
    # Drop the orphan value too.
    argv.remove("claude-code")
    with pytest.raises(SystemExit) as exc:
        _parse(argv)
    assert exc.value.code != 0


# ── end-to-end main() routing ─────────────────────────────────────────────

def test_main_returns_0_on_successful_telemetry() -> None:
    fake_response = {"statusCode": 200, "body": {"success": True, "requestId": "r1"}}
    with patch(
        "alibabacloud.mcp_proxy.telemetry.report_telemetry",
        return_value=fake_response,
    ) as mock_report:
        rc = main(_REQUIRED_ARGS)
    assert rc == 0
    assert mock_report.called
    sent_payload = mock_report.call_args.args[0]
    assert sent_payload["clientName"] == "claude-code"


def test_main_returns_1_on_telemetry_failure() -> None:
    with patch(
        "alibabacloud.mcp_proxy.telemetry.report_telemetry",
        return_value=None,
    ):
        rc = main(_REQUIRED_ARGS)
    assert rc == 1


def test_main_returns_1_on_backend_success_false(capsys) -> None:
    fake_response = {
        "statusCode": 200,
        "body": {"success": False, "code": "BadField", "message": "nope"},
    }
    with patch(
        "alibabacloud.mcp_proxy.telemetry.report_telemetry",
        return_value=fake_response,
    ):
        rc = main(_REQUIRED_ARGS)
    assert rc == 1
    err = capsys.readouterr().err
    assert "rejected by backend" in err


def test_main_swallows_unexpected_exception(capsys) -> None:
    with patch(
        "alibabacloud.mcp_proxy.telemetry.report_telemetry",
        side_effect=RuntimeError("boom"),
    ):
        rc = main(_REQUIRED_ARGS)
    assert rc == 1
    assert "telemetry call raised unexpectedly" in capsys.readouterr().err


def test_plugin_telemetry_command_is_routed_at_top_level() -> None:
    # Sanity check: argparse picks up the top-level subcommand name.
    args = _parse(_REQUIRED_ARGS)
    assert args.command == "plugin-telemetry"
