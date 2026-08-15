from __future__ import annotations

import json

import psutil

from alibabacloud.mcp_proxy import session_marker


class _FakeProcess:
    """Minimal psutil.Process stand-in for tests."""

    def __init__(self, pid: int, ppid: int, name: str) -> None:
        self._pid = pid
        self._ppid = ppid
        self._name = name

    def ppid(self) -> int:
        return self._ppid

    def name(self) -> str:
        return self._name


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


def test_find_agent_pid_walks_up_and_finds_agent(monkeypatch) -> None:
    # proxy(100) -> launcher(200) -> claude(300) -> explorer(400)
    processes = {
        100: _FakeProcess(100, 200, "python.exe"),
        200: _FakeProcess(200, 300, "launcher"),
        300: _FakeProcess(300, 400, "claude.exe"),
        400: _FakeProcess(400, 0, "explorer.exe"),
    }
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(
        session_marker.psutil, "Process", lambda pid: processes[pid]
    )

    assert session_marker.find_agent_pid() == 300


def test_find_agent_pid_matches_agent_without_exe_suffix(monkeypatch) -> None:
    processes = {
        100: _FakeProcess(100, 200, "python.exe"),
        200: _FakeProcess(200, 300, "claude"),  # Unix 风格: 无 .exe
    }
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(
        session_marker.psutil, "Process", lambda pid: processes[pid]
    )

    assert session_marker.find_agent_pid() == 200


def test_find_agent_pid_returns_none_without_agent(monkeypatch) -> None:
    def fake_process(pid: int):
        return _FakeProcess(pid, pid + 100, f"proc-{pid}")

    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker.psutil, "Process", fake_process)

    assert session_marker.find_agent_pid() is None


def test_find_agent_pid_stops_on_missing_process(monkeypatch) -> None:
    def fake_process(pid: int):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker.psutil, "Process", fake_process)

    assert session_marker.find_agent_pid() is None


def test_find_agent_pid_stops_at_system_process(monkeypatch) -> None:
    processes = {
        100: _FakeProcess(100, 1, "python.exe"),  # 父进程是 PID 1
    }
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(
        session_marker.psutil, "Process", lambda pid: processes[pid]
    )

    assert session_marker.find_agent_pid() is None
