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


def test_find_agent_pid_walks_up_and_finds_agent(monkeypatch) -> None:
    # proxy(100) -> launcher(200) -> claude(300) -> explorer(400)
    parents = {100: 200, 200: 300, 300: 400}
    names = {200: "launcher", 300: "claude", 400: "explorer"}
    monkeypatch.setattr(session_marker.sys, "platform", "linux")
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker, "_parent_pid", parents.get)
    monkeypatch.setattr(session_marker, "_process_name", names.get)

    assert session_marker.find_agent_pid() == 300


def test_find_agent_pid_returns_none_without_agent(monkeypatch) -> None:
    monkeypatch.setattr(session_marker.sys, "platform", "linux")
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker, "_parent_pid", lambda pid: pid + 100)
    monkeypatch.setattr(
        session_marker, "_process_name", lambda pid: f"proc-{pid}"
    )

    assert session_marker.find_agent_pid() is None


def test_find_agent_pid_stops_at_unknown_parent(monkeypatch) -> None:
    monkeypatch.setattr(session_marker.sys, "platform", "linux")
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker, "_parent_pid", lambda pid: None)
    monkeypatch.setattr(
        session_marker, "_process_name", lambda pid: "claude"
    )

    assert session_marker.find_agent_pid() is None


def test_windows_agent_pid_script_matches_agent_names() -> None:
    script = session_marker._windows_agent_pid_script(100)
    # 脚本应包含所有 agent 名称(小写)用于匹配
    for name in session_marker._AGENT_BINARIES:
        assert name.lower() in script
    # 包含 .exe 剥离逻辑与父进程遍历
    assert ".exe" in script
    assert "ParentProcessId" in script


def test_find_agent_pid_windows_uses_single_script_call(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str | None:
        calls.append(cmd)
        return "300"  # 模拟脚本输出找到的 agent PID

    monkeypatch.setattr(session_marker.sys, "platform", "win32")
    monkeypatch.setattr(session_marker.os, "getpid", lambda: 100)
    monkeypatch.setattr(session_marker, "_run", fake_run)

    assert session_marker.find_agent_pid() == 300
    # Windows 分支只做一次 PowerShell 调用
    assert len(calls) == 1
    assert calls[0][0] == "powershell"
    assert "Get-CimInstance" in calls[0][-1]


def test_run_returns_none_on_timeout(monkeypatch) -> None:
    import subprocess as real_subprocess

    def fake_check_output(*args, **kwargs):
        raise real_subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(session_marker.subprocess, "check_output", fake_check_output)

    assert session_marker._run(["ps", "-o", "ppid=", "-p", "1"]) is None
