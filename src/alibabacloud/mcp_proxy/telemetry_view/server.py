from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web

_LOGGER = logging.getLogger(__name__)

from alibabacloud.mcp_proxy.telemetry_view.data import (
    SessionMeta,
    TraceFileWatcher,
    _safe_stat,
    build_span_tree,
    parse_jsonl_file,
)

_STATIC_DIR = Path(__file__).parent / "static"
_SSE_HEARTBEAT_SECONDS = 15.0


@web.middleware
async def _api_no_keepalive_no_cache(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    """
    Force ``Connection: close`` + ``Cache-Control: no-store`` on dynamic JSON API responses.

    Chrome aggressively reuses HTTP/1.1 keep-alive connections from its socket pool.
    When aiohttp closes an idle connection while Chrome is mid-request on it, the
    request hangs (write succeeds into the TCP buffer, no response ever arrives).
    Forcing close on JSON responses sidesteps the race; SSE keeps keep-alive.
    """
    response = await handler(request)
    if request.path.startswith("/api/") and request.path != "/api/events":
        response.headers["Cache-Control"] = "no-store"
        response.force_close()
    return response


def create_app(
    index: dict[tuple[str, str], SessionMeta],
    data_dirs: list[Path],
) -> web.Application:
    app = web.Application(middlewares=[_api_no_keepalive_no_cache])
    app["index"] = index
    app["data_dirs"] = data_dirs
    app["sse_clients"] = []
    # detail-page cache keyed by (client, session_id) -> (mtime_ns, file_size, spans)
    app["detail_cache"] = {}

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

    all_sessions = list(index.values())
    client_counts: dict[str, int] = {}
    total_errors = 0
    for s in all_sessions:
        client_counts[s.client] = client_counts.get(s.client, 0) + 1
        if s.has_errors:
            total_errors += 1
    total_all = len(all_sessions)

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
        "stats": {
            "total_sessions": total_all,
            "client_counts": client_counts,
            "error_sessions": total_errors,
            "success_rate": round((total_all - total_errors) / total_all * 100, 1) if total_all else 0,
        },
    })


async def handle_session_detail(request: web.Request) -> web.Response:
    index = request.app["index"]
    client = request.match_info["client"]
    session_id = request.match_info["session_id"]

    key = (client, session_id)
    if key not in index:
        return web.json_response({"error": "Session not found"}, status=404)

    meta = index[key]
    cache = request.app["detail_cache"]
    stat_result = await asyncio.to_thread(_safe_stat, meta.file_path)
    if stat_result is None:
        return web.json_response({"error": "Trace file is not readable"}, status=404)

    cache_key = (client, session_id)
    cached = cache.get(cache_key)
    if (
        cached is not None
        and cached[0] == stat_result.st_mtime_ns
        and cached[1] == stat_result.st_size
    ):
        return web.Response(body=cached[2], content_type="application/json")

    spans = await asyncio.to_thread(parse_jsonl_file, meta.file_path)
    tree = build_span_tree(spans)

    turn_numbers: set[int] = set()
    tool_count = 0
    skill_count = 0
    prompt_count = 0
    success_count = 0
    failure_count = 0
    for span in spans:
        event = span.get("event")
        turn = span.get("turn")
        if turn is not None:
            turn_numbers.add(turn)
        if event == "prompt":
            prompt_count += 1
        elif event == "skill_invocation":
            skill_count += 1
        elif event == "tool":
            if (span.get("tool_name") or "").lower() == "skill":
                skill_count += 1
            else:
                tool_count += 1
            if span.get("status") == "success":
                success_count += 1
            elif span.get("status") == "failure":
                failure_count += 1

    total_calls = success_count + failure_count

    payload = {
        "client": client,
        "session_id": session_id,
        "start_time": meta.start_time,
        "last_activity": meta.last_activity,
        "spans": tree,
        "stats": {
            "turns": len(turn_numbers),
            "tools": tool_count,
            "skills": skill_count,
            "prompts": prompt_count,
            "success": success_count,
            "failure": failure_count,
            "success_rate": round(success_count / total_calls * 100, 1) if total_calls else 100.0,
        },
    }
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    cache[cache_key] = (stat_result.st_mtime_ns, stat_result.st_size, body)
    return web.Response(body=body, content_type="application/json")


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
    try:
        await response.prepare(request)
    except (ConnectionResetError, asyncio.CancelledError) as exc:
        _LOGGER.debug("SSE prepare aborted (client disconnected): %s", exc)
        return response
    except Exception as exc:  # noqa: BLE001 — aiohttp's ClientConnectionResetError lives outside this scope
        if exc.__class__.__name__ == "ClientConnectionResetError":
            _LOGGER.debug("SSE prepare aborted (client disconnected): %s", exc)
            return response
        raise

    queue: asyncio.Queue[str] = asyncio.Queue()
    request.app["sse_clients"].append(queue)

    async def _safe_write(payload: str) -> bool:
        try:
            await response.write(payload.encode("utf-8"))
            return True
        except (ConnectionResetError, asyncio.CancelledError):
            return False
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "ClientConnectionResetError":
                return False
            raise

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                if not await _safe_write(": ping\n\n"):
                    break
                continue
            if not await _safe_write(data):
                break
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        if queue in request.app["sse_clients"]:
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
