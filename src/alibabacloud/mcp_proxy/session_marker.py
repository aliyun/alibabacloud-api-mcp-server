from __future__ import annotations

import json
import os
import subprocess
import time

_AGENT_BINARIES = ("claude", "codex", "QoderWork")
_MCP_SESSION_DIR = "~/.cache/alibabacloud-agent-toolkit/mcp-sessions"


def find_agent_pid() -> int | None:
    """Walk up the process tree to find the agent PID for hook correlation."""
    pid = os.getpid()
    for _ in range(10):
        try:
            ppid = int(
                subprocess.check_output(
                    ["ps", "-o", "ppid=", "-p", str(pid)],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            )
        except Exception:
            break
        if ppid <= 1:
            break
        try:
            comm = (
                subprocess.check_output(
                    ["ps", "-o", "comm=", "-p", str(ppid)],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                .strip()
                .rsplit("/", 1)[-1]
            )
        except Exception:
            break
        if comm in _AGENT_BINARIES:
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
