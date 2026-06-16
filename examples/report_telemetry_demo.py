#!/usr/bin/env python3
"""
Runnable demo for the ReportTelemetry utility.

Usage:
    # 1. Configure Alibaba Cloud credentials (any one of these works):
    export ALIBABA_CLOUD_ACCESS_KEY_ID="<your-ak-id>"
    export ALIBABA_CLOUD_ACCESS_KEY_SECRET="<your-ak-secret>"
    # or use ~/.alibabacloud/credentials, RAM role on ECS, etc.

    # 2. Run with the bundled sample payload:
    python3 examples/report_telemetry_demo.py

    # 3. Run with a custom payload file:
    python3 examples/report_telemetry_demo.py --payload examples/telemetry_sample.json

    # 4. Run the async variant:
    python3 examples/report_telemetry_demo.py --async

    # 5. Verbose logging (shows retry warnings, request lifecycle):
    python3 examples/report_telemetry_demo.py --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Allow `python3 examples/report_telemetry_demo.py` to work without install:
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from alibabacloud.mcp_proxy.telemetry import (  # noqa: E402
    report_telemetry,
    report_telemetry_async,
)


def _default_payload() -> dict:
    """Build a fully-populated sample payload matching the backend schema."""
    now = datetime.now(UTC)
    start_ts = now.isoformat(timespec="milliseconds")
    end_ts = now.isoformat(timespec="milliseconds")
    return {
        # ── required fields ────────────────────────────────────────────────
        "clientName": "alibabacloud-mcp-proxy",
        "eventType": "tool_call",
        "startTimestamp": start_ts,
        "toolName": "report_telemetry_demo",
        "sessionId": f"sess-{uuid.uuid4().hex[:12]}",
        "status": "success",
        # ── optional fields ────────────────────────────────────────────────
        "endTimestamp": end_ts,
        "turn": 1,
        "mcpTool": "demo.mcp.toolkit",
        "cliCommand": "python3 examples/report_telemetry_demo.py",
        "eventTag": "Smoke-test the ReportTelemetry endpoint",
        "skillName": "telemetry-smoke",
        "toolRequestId": f"req-{uuid.uuid4().hex[:16]}",
        "errorMessage": "",
        "pluginName": "alibabacloud",
    }


def _load_payload(path: str | None) -> dict:
    if not path:
        return _default_payload()
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"Payload file must contain a JSON object, got {type(data).__name__}")
    return data


def _print_result(label: str, response: dict | None) -> int:
    print(f"\n=== {label} ===")
    if response is None:
        print("Result: FAILED (see logs above for the underlying error)")
        return 1
    print(f"Status: {response.get('statusCode')}")
    print("Body:")
    print(json.dumps(response.get("body"), ensure_ascii=False, indent=2, default=str))
    print("Headers:")
    print(json.dumps(response.get("headers"), ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ReportTelemetry demo client")
    parser.add_argument("--payload", help="Path to a JSON file containing the payload")
    parser.add_argument(
        "--async", dest="use_async", action="store_true",
        help="Use the async entrypoint instead of the sync one",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not (
        os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
        or os.environ.get("ALIBABACLOUD_ACCESS_KEY_ID")
        or Path.home().joinpath(".alibabacloud", "credentials").exists()
        or Path.home().joinpath(".aliyun", "config.json").exists()
    ):
        print(
            "WARNING: no Alibaba Cloud credentials detected in env or default chain.\n"
            "         Set ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET, "
            "or configure ~/.alibabacloud/credentials.\n",
            file=sys.stderr,
        )

    payload = _load_payload(args.payload)
    print("Payload to be sent:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.use_async:
        response = asyncio.run(report_telemetry_async(payload))
        return _print_result("ASYNC report_telemetry_async", response)

    response = report_telemetry(payload)
    return _print_result("SYNC report_telemetry", response)


if __name__ == "__main__":
    raise SystemExit(main())
