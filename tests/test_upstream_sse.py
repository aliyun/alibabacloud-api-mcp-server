from __future__ import annotations

import asyncio
import json

import anyio
import pytest
from aiohttp import web

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig, RetrySettings
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
from alibabacloud.mcp_proxy.transport.upstream_sse import SseConnectionFactory


@pytest.mark.asyncio
async def test_legacy_session_404_reconnects_and_retries_request(
    aiohttp_server,
) -> None:
    session_queues: dict[str, asyncio.Queue[dict[str, object]]] = {}
    created_sessions: list[str] = []
    tools_list_sessions: list[str] = []

    async def handle_sse(request: web.Request) -> web.StreamResponse:
        session_id = f"session-{len(created_sessions) + 1}"
        created_sessions.append(session_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        session_queues[session_id] = queue

        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)
        await response.write(
            f"event: endpoint\ndata: /message?sessionId={session_id}\n\n".encode()
        )

        try:
            while True:
                message = await queue.get()
                data = json.dumps(message, separators=(",", ":"))
                await response.write(f"event: message\ndata: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            return response

    async def handle_message(request: web.Request) -> web.Response:
        session_id = request.query["sessionId"]
        payload = await request.json()
        method = payload["method"]

        if method == "initialize":
            await session_queues[session_id].put(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                }
            )
            return web.Response(status=202)

        if method == "notifications/initialized":
            return web.Response(status=202)

        if method == "tools/list":
            tools_list_sessions.append(session_id)
            if session_id == "session-1":
                return web.json_response(
                    {"error": f"Session not found: {session_id}"},
                    status=404,
                )
            await session_queues[session_id].put(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"tools": []},
                }
            )
            return web.Response(status=202)

        raise AssertionError(f"Unexpected method: {method}")

    class TokenProvider:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def get_token(self, *, force_refresh: bool = False) -> str:
            self.calls.append(force_refresh)
            return "test-token"

    app = web.Application()
    app.router.add_get("/sse", handle_sse)
    app.router.add_post("/message", handle_message)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/sse"))
    config = AlibabaCloudProxyConfig.from_mapping(
        {
            "server_url": server_url,
            "connect_timeout_seconds": "1",
            "read_timeout_seconds": "30",
        }
    )
    factory = SseConnectionFactory(config, server_url)
    token_provider = TokenProvider()

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        session = ReconnectingSession(
            factory,
            token_provider,
            RetrySettings(
                max_attempts=2,
                base_delay_seconds=0.01,
                max_delay_seconds=0.01,
            ),
        )
        try:
            with anyio.fail_after(1):
                result = await session.list_tools()
        finally:
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert created_sessions == ["session-1", "session-2"]
    assert tools_list_sessions == ["session-1", "session-2"]
    assert token_provider.calls == [False, False]


@pytest.mark.asyncio
async def test_initialize_503_reconnects_with_a_new_legacy_sse_session(
    aiohttp_server,
) -> None:
    session_queues: dict[str, asyncio.Queue[dict[str, object]]] = {}
    created_sessions: list[str] = []
    initialize_sessions: list[str] = []
    tools_list_sessions: list[str] = []

    async def handle_sse(request: web.Request) -> web.StreamResponse:
        session_id = f"session-{len(created_sessions) + 1}"
        created_sessions.append(session_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        session_queues[session_id] = queue

        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)
        await response.write(
            f"event: endpoint\ndata: /message?sessionId={session_id}\n\n".encode()
        )

        try:
            while True:
                message = await queue.get()
                data = json.dumps(message, separators=(",", ":"))
                await response.write(f"event: message\ndata: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            return response

    async def handle_message(request: web.Request) -> web.Response:
        session_id = request.query["sessionId"]
        payload = await request.json()
        method = payload["method"]

        if method == "initialize":
            initialize_sessions.append(session_id)
            if session_id == "session-1":
                return web.Response(status=503, text="Service Unavailable")
            await session_queues[session_id].put(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                }
            )
            return web.Response(status=202)

        if method == "notifications/initialized":
            return web.Response(status=202)

        if method == "tools/list":
            tools_list_sessions.append(session_id)
            await session_queues[session_id].put(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"tools": []},
                }
            )
            return web.Response(status=202)

        raise AssertionError(f"Unexpected method: {method}")

    class TokenProvider:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def get_token(self, *, force_refresh: bool = False) -> str:
            self.calls.append(force_refresh)
            return "test-token"

    app = web.Application()
    app.router.add_get("/sse", handle_sse)
    app.router.add_post("/message", handle_message)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/sse"))
    config = AlibabaCloudProxyConfig.from_mapping(
        {
            "server_url": server_url,
            "connect_timeout_seconds": "1",
            "read_timeout_seconds": "30",
        }
    )
    factory = SseConnectionFactory(config, server_url)
    token_provider = TokenProvider()

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        session = ReconnectingSession(
            factory,
            token_provider,
            RetrySettings(
                max_attempts=2,
                base_delay_seconds=0.01,
                max_delay_seconds=0.01,
            ),
        )
        try:
            with anyio.fail_after(1):
                result = await session.list_tools()
        finally:
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert created_sessions == ["session-1", "session-2"]
    assert initialize_sessions == ["session-1", "session-2"]
    assert tools_list_sessions == ["session-2"]
    assert token_provider.calls == [False, False]
