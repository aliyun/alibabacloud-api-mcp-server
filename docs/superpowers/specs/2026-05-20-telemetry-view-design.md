# Telemetry View — Local Tracing Visualization Server

## Overview

A local web server launched via `uvx alibabacloud.mcp-proxy telemetry-view` that parses JSONL trace files and presents an interactive tracing UI in the browser. Displays agent client sessions (Claude Code, VS Code, Copilot CLI, Codex, Qoderwork) with span hierarchy, timeline visualization, and live updates.

## CLI Interface

```
uvx alibabacloud.mcp-proxy telemetry-view [--port PORT] [--no-open]
```

- `--port`: Local server port (default: 18321, chosen to avoid common conflicts)
- `--no-open`: Skip auto-opening the browser

Startup prints the URL and data directory summary, then opens the default browser.

## Architecture

```
CLI (telemetry-view subcommand)
  → aiohttp async server
    ├── Static file handler (serves SPA)
    ├── REST API (/api/sessions, /api/sessions/{client}/{session_id})
    ├── SSE endpoint (/api/events)
    └── File watcher (asyncio, 2s poll interval)
  → Data sources (merged):
    1. $ALIBABACLOUD_TELEMETRY_STATE_DIR (if set)
    2. ~/.cache/alibabacloud-agent-toolkit/telemetry/
    3. /tmp/alibabacloud-agent-toolkit-telemetry-<uid>/
```

Each directory is scanned for `{client}/traces/*.jsonl`.

## Tech Stack

- **Backend**: Python 3.10+, `aiohttp` (new required dependency)
- **Frontend**: Vanilla HTML/JS/CSS SPA (no build step, bundled as static assets)
- **Real-time**: Server-Sent Events (SSE) for live span/session updates
- **Distribution**: Works seamlessly with `uvx` — zero build step for users

### Python 3.10 Compatibility Constraints

- Use `from __future__ import annotations` in all modules (enables `X | Y` union syntax)
- No `match` statements — use if/elif chains
- No `type X = ...` aliases (3.12+) — use `TypeAlias` from `typing_extensions` if needed
- No `asyncio.TaskGroup` (3.11+) — rely on aiohttp's built-in concurrency
- No `except*` (3.11+) — use standard exception handling

## Package Structure

```
src/alibabacloud/mcp_proxy/
├── telemetry_view/
│   ├── __init__.py
│   ├── server.py          # aiohttp app, routes, SSE
│   ├── data.py            # JSONL parsing, session index, file watching
│   └── static/
│       ├── index.html     # SPA shell
│       ├── app.js         # Client-side routing, rendering, SSE
│       └── style.css      # Themes (light/dark), layout, components
```

## Data Sources

Directory resolution:

```python
def resolve_data_dirs() -> list[Path]:
    dirs = []
    env_dir = os.environ.get("ALIBABACLOUD_TELEMETRY_STATE_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.append(Path.home() / ".cache/alibabacloud-agent-toolkit/telemetry")
    dirs.append(Path(f"/tmp/alibabacloud-agent-toolkit-telemetry-{os.getuid()}"))
    return [d for d in dirs if d.exists()]
```

File structure within each dir:
```
<telemetry-dir>/
├── claude-code/traces/*.jsonl
├── codex/traces/*.jsonl
├── vscode/traces/*.jsonl
├── copilot-cli/traces/*.jsonl
└── qoderwork/traces/*.jsonl
```

## JSONL Data Model

Based on `local_audit_trace_jsonl_info.md`.

### Common Fields (all events)

| Field | Type | Description |
|-------|------|-------------|
| `event` | `string` | Enum: `prompt`, `skill_invocation`, `tool_start`, `tool_end`, `turn_end` |
| `span_id` | `string` | Unique span identifier |
| `parent_span_id` | `string \| null` | Parent span. `null` only for `prompt` (root) |
| `turn` | `int` | Zero-based turn counter |
| `start_timestamp` | `string` | ISO 8601 with ms |
| `end_timestamp` | `string` | ISO 8601 with ms |
| `session_id` | `string` | Session UUID |
| `client` | `string` | Enum: `claude-code`, `vscode`, `copilot-cli`, `codex`, `qoderwork` |

### Event-Specific Fields

**`prompt`**: `prompt` (string, sanitized user text)

**`skill_invocation`**: `tool_name` (always "Skill"), `skill_name`, `plugin_name`, `status` (always "success")

**`tool_start`**: `tool_name`, `tool_use_id`, `tool_input` (object, sanitized)

**`tool_end`**: `tool_name`, `tool_use_id`, `status` ("success"|"failure"), `error_message` (string|null, classified code like "NoPermission", "Throttling"), `request_id` (string|null), `duration_ms` (int), `tool_response` (array|string|null), `truncated` (bool)

**`turn_end`**: `stop_reason` ("Stop"|"StopFailure")

### Span Merging

`tool_start` and `tool_end` with the same `span_id` are merged into a single logical `tool` span combining fields from both events.

### Hierarchy

- `prompt` spans are roots (one per turn, `parent_span_id: null`)
- All other spans reference their parent prompt via `parent_span_id`
- Children sorted by `start_timestamp`

## REST API

### GET /api/sessions

Query params:
- `page` (int, default 1)
- `page_size` (int, default 20)
- `client` (string, filter by client type)
- `q` (string, keyword search across prompt text and tool names)
- `start_time` (ISO 8601, filter sessions starting after)
- `end_time` (ISO 8601, filter sessions ending before)
- `sort` (default: `last_activity_desc`)

Response:
```json
{
  "sessions": [{
    "client": "claude-code",
    "session_id": "3028a555-...",
    "first_prompt_preview": "给我再来一个ACK的示例",
    "start_time": "2026-05-20T06:11:20.455Z",
    "last_activity": "2026-05-20T06:17:02.156Z",
    "span_count": 16,
    "turn_count": 4,
    "has_errors": false
  }],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

### GET /api/sessions/{client}/{session_id}

Response: full trace with nested span tree.

```json
{
  "client": "claude-code",
  "session_id": "3028a555-...",
  "start_time": "2026-05-20T06:11:20.455Z",
  "last_activity": "2026-05-20T06:17:02.156Z",
  "spans": [{
    "span_id": "2d2fb46005e44ed1",
    "parent_span_id": null,
    "event": "prompt",
    "turn": 0,
    "start_timestamp": "2026-05-20T06:11:20.455Z",
    "end_timestamp": "2026-05-20T06:13:02.064Z",
    "prompt": "给我再来一个ACK的示例",
    "children": [{
      "span_id": "skill_..._0",
      "event": "skill_invocation",
      "skill_name": "alibabacloud-core:alibabacloud-sdk-usage",
      "..."
    }, {
      "span_id": "toolu_bdrk_01N7Xp...",
      "event": "tool",
      "tool_name": "AlibabaCloud___GetApiDefinition",
      "duration_ms": 2031,
      "status": "success",
      "..."
    }]
  }]
}
```

### GET /api/events (SSE)

Server-Sent Events stream:

```
event: session_updated
data: {"client":"claude-code","session_id":"3028a555-...","last_activity":"...","span_count":17}

event: new_spans
data: {"client":"claude-code","session_id":"3028a555-...","spans":[{...}]}
```

## Frontend

### SPA Routing (hash-based)

- `#/` — Session list (home)
- `#/trace/{client}/{session_id}` — Trace detail

### Home Page

- Header: logo + title + theme toggle
- Filter bar: client dropdown, time range pickers, keyword search
- Session cards: client logo, client name, session ID, start/end times, first prompt preview
- Pagination controls
- Sorted by last_activity descending (most recent first)
- Live: SSE updates modify card metadata in-place

### Trace Detail Page

- Header: back button, client + session info, theme toggle
- Split layout:
  - Left (40%): Collapsible span tree with indentation
  - Right (60%): Gantt-style timeline bars scaled to session duration
- Bottom panel: Span detail (appears on span click)
  - Shows: event type, tool name, status, duration, timestamps
  - Expandable sections: tool_input (JSON), tool_response (JSON, with truncation warning)
  - Error badge when status=failure with error_message code
- Live: SSE appends new spans without full reload

### Span Visual Encoding

| Event Type | Color (Light) | Color (Dark) | Icon |
|-----------|---------------|--------------|------|
| prompt | #1976d2 (blue) | #64b5f6 | chat bubble |
| tool | #f57c00 (orange) | #ffb74d | wrench |
| skill_invocation | #388e3c (green) | #81c784 | lightning |
| turn_end | #757575 (gray) | #bdbdbd | flag |
| error (failure) | #d32f2f (red) | #ef5350 | alert |

### Client Logos

SVG icons bundled as data URIs in JS:
- `claude-code` — Anthropic Claude logo
- `vscode` — VS Code logo
- `copilot-cli` — GitHub Copilot logo
- `codex` — OpenAI Codex logo
- `qoderwork` — Qoderwork logo (custom/placeholder)

### Themes

**Light (default)**: White background, #f8f9fa surfaces, #202124 text, Google Material palette.

**Dark**: #1a1a2e background, #16213e surfaces, #e0e0e0 text, vibrant accent colors.

Toggle in top-right corner, persisted to localStorage.

## File Watching & Real-time

- Backend polls file sizes every 2 seconds (cross-platform, no inotify dep)
- On change: seeks to last offset, reads new lines, updates in-memory index
- New files detected by directory scan
- Changes pushed to SSE clients via `asyncio.Queue` per connection
- SSE uses `id:` field for reconnection catch-up

## In-Memory Session Index

Built on startup by scanning all JSONL files. Updated incrementally.

```python
sessions_index[("claude-code", "3028a555-...")] = {
    "client": "claude-code",
    "session_id": "3028a555-...",
    "file_path": Path("..."),
    "file_offset": 1842,
    "start_time": "2026-05-20T06:11:20.455Z",
    "last_activity": "2026-05-20T06:17:02.156Z",
    "first_prompt_preview": "给我再来一个ACK的...",
    "span_count": 16,
    "turn_count": 4,
    "has_errors": False,
}
```

## CLI Integration

Added to `cli.py` as a new subcommand:

```python
telemetry_view_parser = subparsers.add_parser(
    "telemetry-view",
    help="Launch local web UI to browse telemetry traces.",
)
telemetry_view_parser.add_argument(
    "--port", type=int, default=18321,
    help="Local server port (default: 18321).",
)
telemetry_view_parser.add_argument(
    "--no-open", action="store_true",
    help="Don't auto-open browser.",
)
```

Startup flow:
1. Resolve data directories
2. Build session index
3. Start aiohttp server on specified port
4. Print: `Telemetry viewer: http://localhost:{port}`
5. Print: `Watching {n} directories, found {m} sessions`
6. Open browser (unless --no-open)
7. Run until Ctrl+C (graceful shutdown)

## Dependencies

Update `pyproject.toml`:
```toml
requires-python = ">=3.10"

dependencies = [
    ...,
    "aiohttp>=3.9.0",
]
```

Note: The `requires-python` is lowered from `>=3.13` to `>=3.10` for broader compatibility. Existing proxy code should be audited for 3.13-only features, but the telemetry-view module will strictly target 3.10+.
