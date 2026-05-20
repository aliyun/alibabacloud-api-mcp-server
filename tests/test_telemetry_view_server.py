from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from alibabacloud.mcp_proxy.telemetry_view.server import create_app
from alibabacloud.mcp_proxy.telemetry_view.data import build_session_index


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    traces_dir = tmp_path / "claude-code" / "traces"
    traces_dir.mkdir(parents=True)
    jsonl_file = traces_dir / "sess-api-test.jsonl"
    lines = [
        {
            "event": "prompt", "span_id": "sp-1", "parent_span_id": None,
            "turn": 0, "start_timestamp": "2026-05-20T06:11:20.455Z",
            "end_timestamp": "2026-05-20T06:13:02.064Z",
            "session_id": "sess-api-test", "client": "claude-code",
            "prompt": "Help me with ACK cluster setup",
        },
        {
            "event": "tool_start", "span_id": "sp-2", "parent_span_id": "sp-1",
            "turn": 0, "start_timestamp": "2026-05-20T06:11:25.000Z",
            "end_timestamp": "2026-05-20T06:11:25.000Z",
            "session_id": "sess-api-test", "client": "claude-code",
            "tool_name": "AlibabaCloud___GetApiDefinition",
            "tool_use_id": "toolu_t1", "tool_input": {"product": "CS"},
        },
        {
            "event": "tool_end", "span_id": "sp-2", "parent_span_id": "sp-1",
            "turn": 0, "start_timestamp": "2026-05-20T06:11:25.000Z",
            "end_timestamp": "2026-05-20T06:11:27.000Z",
            "session_id": "sess-api-test", "client": "claude-code",
            "tool_name": "AlibabaCloud___GetApiDefinition",
            "tool_use_id": "toolu_t1", "status": "success",
            "error_message": None, "request_id": "R1",
            "duration_ms": 2000, "tool_response": [{"type": "text", "text": "{}"}],
            "truncated": False,
        },
        {
            "event": "turn_end", "span_id": "sp-3", "parent_span_id": "sp-1",
            "turn": 0, "start_timestamp": "2026-05-20T06:13:02.064Z",
            "end_timestamp": "2026-05-20T06:13:02.064Z",
            "session_id": "sess-api-test", "client": "claude-code",
            "stop_reason": "Stop",
        },
    ]
    jsonl_file.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return tmp_path


@pytest.fixture
async def client(trace_dir: Path, aiohttp_client) -> TestClient:
    index = build_session_index([trace_dir])
    app = create_app(index=index, data_dirs=[trace_dir])
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_get_sessions_returns_list(client: TestClient) -> None:
    resp = await client.get("/api/sessions")
    assert resp.status == 200
    data = await resp.json()
    assert "sessions" in data
    assert data["total"] == 1
    assert data["sessions"][0]["client"] == "claude-code"
    assert data["sessions"][0]["session_id"] == "sess-api-test"
    assert "Help me with ACK" in data["sessions"][0]["first_prompt_preview"]


@pytest.mark.asyncio
async def test_get_sessions_pagination(client: TestClient) -> None:
    resp = await client.get("/api/sessions?page=1&page_size=10")
    assert resp.status == 200
    data = await resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_get_sessions_filter_by_client(client: TestClient) -> None:
    resp = await client.get("/api/sessions?client=codex")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_session_detail_returns_tree(client: TestClient) -> None:
    resp = await client.get("/api/sessions/claude-code/sess-api-test")
    assert resp.status == 200
    data = await resp.json()
    assert data["client"] == "claude-code"
    assert data["session_id"] == "sess-api-test"
    assert len(data["spans"]) == 1  # one root prompt
    root = data["spans"][0]
    assert root["event"] == "prompt"
    assert len(root["children"]) == 2  # merged tool + turn_end


@pytest.mark.asyncio
async def test_get_session_detail_not_found(client: TestClient) -> None:
    resp = await client.get("/api/sessions/claude-code/nonexistent")
    assert resp.status == 404
