from __future__ import annotations

import json
import os
import subprocess
import sys
import time

_AGENT_BINARIES = ("claude", "codex", "QoderWork")
_MCP_SESSION_DIR = "~/.cache/alibabacloud-agent-toolkit/mcp-sessions"

# 子进程调用超时(秒)。在 Windows 上,Git/MSYS 提供的 `ps` 可执行文件查询
# Windows 进程时可能永不退出,PowerShell 冷启动也较慢;超时保证该调用
# 永远不会挂起(它运行在 asyncio 事件循环线程中,一旦挂起会拖垮整个代理)。
_SUBPROCESS_TIMEOUT = 5.0


def _run(cmd: list[str]) -> str | None:
    """Run a command and return its trimmed stdout, or None on failure/timeout."""
    try:
        out = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except Exception:
        return None
    return out.strip()


def _windows_agent_pid_script(start_pid: int) -> str:
    """Build a single PowerShell script that walks the process tree once.

    One WMI snapshot plus in-memory traversal keeps latency at a single
    PowerShell cold start (~1-2s) while still never hanging.
    """
    names = ", ".join(f"'{name.lower()}'" for name in _AGENT_BINARIES)
    return (
        "$procs = @{{}}\n"
        "Get-CimInstance Win32_Process | ForEach-Object {{ $procs[$_.ProcessId] = $_ }}\n"
        "$p = {pid}\n"
        "for ($i = 0; $i -lt 10; $i++) {{\n"
        "  if (-not $procs.ContainsKey($p)) {{ break }}\n"
        "  $name = $procs[$p].Name\n"
        "  $pp = [int]$procs[$p].ParentProcessId\n"
        "  if ($pp -le 1) {{ break }}\n"
        "  if ($name -like '*.exe') {{ $name = $name.Substring(0, $name.Length - 4) }}\n"
        "  if ($name.ToLower() -in @({names})) {{ Write-Output $pp; exit 0 }}\n"
        "  $p = $pp\n"
        "}}\n"
        "exit 1"
    ).format(pid=start_pid, names=names)


def _parent_pid(pid: int) -> int | None:
    """Return the parent PID of a process (Unix; Windows uses _windows_agent_pid_script)."""
    out = _run(["ps", "-o", "ppid=", "-p", str(pid)])
    if not out:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _process_name(pid: int) -> str | None:
    """Return the process name (basename, without path) for a PID (Unix)."""
    out = _run(["ps", "-o", "comm=", "-p", str(pid)])
    if not out:
        return None
    return out.rsplit("/", 1)[-1]


def find_agent_pid() -> int | None:
    """Walk up the process tree to find the agent PID for hook correlation."""
    if sys.platform == "win32":
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _windows_agent_pid_script(os.getpid()),
            ]
        )
        if not out:
            return None
        try:
            return int(out)
        except ValueError:
            return None

    pid = os.getpid()
    for _ in range(10):
        ppid = _parent_pid(pid)
        if ppid is None or ppid <= 1:
            break
        comm = _process_name(ppid)
        if comm is None:
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
