from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from alibabacloud.mcp_proxy.telemetry_view.data import (
    TraceFileWatcher,
    build_session_index,
    SessionMeta,
)


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    traces_dir = tmp_path / "claude-code" / "traces"
    traces_dir.mkdir(parents=True)
    jsonl_file = traces_dir / "sess-watch.jsonl"
    line = {
        "event": "prompt",
        "span_id": "sp-1",
        "parent_span_id": None,
        "turn": 0,
        "start_timestamp": "2026-05-20T10:00:00.000Z",
        "end_timestamp": "2026-05-20T10:00:05.000Z",
        "session_id": "sess-watch",
        "client": "claude-code",
        "prompt": "initial prompt",
    }
    jsonl_file.write_text(json.dumps(line) + "\n")
    return tmp_path


@pytest.mark.asyncio
async def test_watcher_detects_appended_lines(trace_dir: Path) -> None:
    index = build_session_index([trace_dir])
    events: list[dict] = []

    async def on_change(event_type: str, data: dict) -> None:
        events.append({"type": event_type, **data})

    watcher = TraceFileWatcher(index, [trace_dir], on_change=on_change, poll_interval=0.1)
    task = asyncio.ensure_future(watcher.run())

    # Append a new line
    await asyncio.sleep(0.05)
    jsonl_file = trace_dir / "claude-code" / "traces" / "sess-watch.jsonl"
    new_line = {
        "event": "tool_start",
        "span_id": "sp-2",
        "parent_span_id": "sp-1",
        "turn": 0,
        "start_timestamp": "2026-05-20T10:00:01.000Z",
        "end_timestamp": "2026-05-20T10:00:01.000Z",
        "session_id": "sess-watch",
        "client": "claude-code",
        "tool_name": "CallCLI",
        "tool_use_id": "toolu_002",
        "tool_input": {"command": "aliyun ecs DescribeInstances"},
    }
    with open(jsonl_file, "a") as f:
        f.write(json.dumps(new_line) + "\n")

    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(events) >= 1
    assert events[0]["type"] == "session_updated"
    assert index[("claude-code", "sess-watch")].span_count == 2


@pytest.mark.asyncio
async def test_watcher_detects_new_files(trace_dir: Path) -> None:
    index = build_session_index([trace_dir])
    events: list[dict] = []

    async def on_change(event_type: str, data: dict) -> None:
        events.append({"type": event_type, **data})

    watcher = TraceFileWatcher(index, [trace_dir], on_change=on_change, poll_interval=0.1)
    task = asyncio.ensure_future(watcher.run())

    await asyncio.sleep(0.05)
    new_file = trace_dir / "claude-code" / "traces" / "sess-new.jsonl"
    line = {
        "event": "prompt",
        "span_id": "sp-new-1",
        "parent_span_id": None,
        "turn": 0,
        "start_timestamp": "2026-05-20T12:00:00.000Z",
        "end_timestamp": "2026-05-20T12:00:10.000Z",
        "session_id": "sess-new",
        "client": "claude-code",
        "prompt": "a brand new session",
    }
    new_file.write_text(json.dumps(line) + "\n")

    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert ("claude-code", "sess-new") in index
