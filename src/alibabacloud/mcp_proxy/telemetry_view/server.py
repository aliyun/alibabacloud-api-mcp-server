from __future__ import annotations

import asyncio
import json
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web

from alibabacloud.mcp_proxy.telemetry_view.data import (
    SessionMeta,
    TraceFileWatcher,
    build_span_tree,
    parse_jsonl_file,
)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    index: dict[tuple[str, str], SessionMeta],
    data_dirs: list[Path],
) -> web.Application:
    app = web.Application()
    app["index"] = index
    app["data_dirs"] = data_dirs
    app["sse_clients"] = []

    app.router.add_get("/api/sessions", handle_sessions)
    app.router.add_get("/api/sessions/{client}/{session_id}", handle_session_detail)
    app.router.add_get("/api/events", handle_sse)
    app.router.add_get("/", handle_index)
    app.router.add_static("/static", _STATIC_DIR, name="static")

    return app


async def handle_index(request: web.Request) -> web.Response | web.FileResponse:
    index_html = _STATIC_DIR / "index.html"
    if index_html.exists():
        return web.FileResponse(index_html)
    return web.Response(text="Telemetry Viewer (UI not yet built)", content_type="text/plain")


async def handle_sessions(request: web.Request) -> web.Response:
    index = request.app["index"]
    page = int(request.query.get("page", "1"))
    page_size = int(request.query.get("page_size", "20"))
    client_filter = request.query.get("client", "")
    query = request.query.get("q", "").lower()
    start_time = request.query.get("start_time", "")
    end_time = request.query.get("end_time", "")

    sessions = list(index.values())

    if client_filter:
        sessions = [s for s in sessions if s.client == client_filter]
    if query:
        sessions = [s for s in sessions if query in s.first_prompt_preview.lower() or query in s.session_id.lower()]
    if start_time:
        sessions = [s for s in sessions if s.start_time >= start_time]
    if end_time:
        sessions = [s for s in sessions if s.last_activity <= end_time]

    sessions.sort(key=lambda s: s.last_activity, reverse=True)
    total = len(sessions)
    start = (page - 1) * page_size
    page_sessions = sessions[start:start + page_size]

    return web.json_response({
        "sessions": [
            {
                "client": s.client,
                "session_id": s.session_id,
                "first_prompt_preview": s.first_prompt_preview,
                "start_time": s.start_time,
                "last_activity": s.last_activity,
                "span_count": s.span_count,
                "turn_count": s.turn_count,
                "has_errors": s.has_errors,
            }
            for s in page_sessions
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


async def handle_session_detail(request: web.Request) -> web.Response:
    index = request.app["index"]
    client = request.match_info["client"]
    session_id = request.match_info["session_id"]

    key = (client, session_id)
    if key not in index:
        return web.json_response({"error": "Session not found"}, status=404)

    meta = index[key]
    spans = parse_jsonl_file(meta.file_path)
    tree = build_span_tree(spans)

    return web.json_response({
        "client": client,
        "session_id": session_id,
        "start_time": meta.start_time,
        "last_activity": meta.last_activity,
        "spans": tree,
    })


async def handle_sse(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    queue: asyncio.Queue[str] = asyncio.Queue()
    request.app["sse_clients"].append(queue)

    try:
        while True:
            data = await queue.get()
            await response.write(data.encode("utf-8"))
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        request.app["sse_clients"].remove(queue)

    return response


async def broadcast_sse(app: web.Application, event_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    message = f"event: {event_type}\ndata: {payload}\n\n"
    for queue in app["sse_clients"]:
        await queue.put(message)


async def run_telemetry_view(port: int, no_open: bool) -> None:
    from alibabacloud.mcp_proxy.telemetry_view.data import (
        build_session_index,
        resolve_data_dirs,
    )

    data_dirs = resolve_data_dirs()
    if not data_dirs:
        print("Warning: No telemetry data directories found.")
        print("Checked:")
        print("  - $ALIBABACLOUD_TELEMETRY_STATE_DIR")
        print("  - ~/.cache/alibabacloud-agent-toolkit/telemetry/")
        print(f"  - /tmp/alibabacloud-agent-toolkit-telemetry-<uid>/")
        data_dirs = []

    index = build_session_index(data_dirs)
    app = create_app(index=index, data_dirs=data_dirs)

    async def on_change(event_type: str, data: dict[str, Any]) -> None:
        sse_data = {k: v for k, v in data.items() if k != "new_spans"}
        await broadcast_sse(app, event_type, sse_data)
        if "new_spans" in data:
            await broadcast_sse(app, "new_spans", {
                "client": data["client"],
                "session_id": data["session_id"],
                "spans": data["new_spans"],
            })

    watcher = TraceFileWatcher(index, data_dirs, on_change=on_change)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    url = f"http://localhost:{port}"
    session_count = len(index)
    dir_count = len(data_dirs)

    print(f"Telemetry viewer: {url}")
    print(f"Watching {dir_count} directories, found {session_count} sessions")

    if not no_open:
        webbrowser.open(url)

    watcher_task = asyncio.ensure_future(watcher.run())
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        watcher_task.cancel()
        await runner.cleanup()
