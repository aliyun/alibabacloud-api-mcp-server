from __future__ import annotations

import json
import os
import time

import psutil

_AGENT_BINARIES = ("claude", "codex", "QoderWork")
# 匹配时忽略大小写与 Windows 的 .exe 后缀
_AGENT_NAMES = frozenset(name.lower() for name in _AGENT_BINARIES)
_MCP_SESSION_DIR = "~/.cache/alibabacloud-agent-toolkit/mcp-sessions"


def _agent_process_name(name: str) -> str:
    """Normalize a process name: strip the Windows .exe suffix and case."""
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name.lower()


def find_agent_pid() -> int | None:
    """Walk up the process tree to find the agent PID for hook correlation.

    Uses psutil so the walk is platform-agnostic and safe to call from the
    asyncio event-loop thread: unlike shelling out to `ps` (which can hang
    forever with the Git/MSYS `ps.exe` on Windows), psutil queries the OS
    process table directly and never blocks indefinitely.
    """
    pid = os.getpid()
    for _ in range(10):
        try:
            proc = psutil.Process(pid)
            ppid = proc.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            break
        if ppid <= 1:
            break
        try:
            parent = psutil.Process(ppid)
            name = _agent_process_name(parent.name())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            break
        if name in _AGENT_NAMES:
            return ppid
        pid = ppid
    return None


def write_mcp_session_marker(mcp_session_id: str | None) -> None:
    """Write the upstream MCP session id keyed by agent PID for hooks."""
    if not mcp_session_id:
        return

    agent_pid = find_agent_pid()
    if not agent_pid:
        return

    mcp_dir = os.path.expanduser(_MCP_SESSION_DIR)
    try:
        os.makedirs(mcp_dir, exist_ok=True)
        path = os.path.join(mcp_dir, f"{agent_pid}.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "mcpSessionId": mcp_session_id,
                    "pid": os.getpid(),
                    "agentPid": agent_pid,
                    "startTimestamp": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                },
                f,
            )
    except Exception:
        pass
