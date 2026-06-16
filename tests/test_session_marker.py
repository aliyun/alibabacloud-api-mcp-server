from __future__ import annotations

import json

from alibabacloud.mcp_proxy import session_marker


def test_write_mcp_session_marker_uses_upstream_session_id(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(session_marker, "_MCP_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(session_marker, "find_agent_pid", lambda: 12345)
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 67890)

    session_marker.write_mcp_session_marker("st_abc123")

    data = json.loads((tmp_path / "12345.json").read_text())
    assert data["mcpSessionId"] == "st_abc123"
    assert data["pid"] == 67890
    assert data["agentPid"] == 12345


def test_write_mcp_session_marker_skips_missing_session_id(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(session_marker, "_MCP_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(session_marker, "find_agent_pid", lambda: 12345)

    session_marker.write_mcp_session_marker("")

    assert not list(tmp_path.iterdir())
