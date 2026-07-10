from __future__ import annotations

import asyncio

import anyio
import httpx
import pytest
from aiohttp import web

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig, RetrySettings
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
from alibabacloud.mcp_proxy.transport.upstream_http import (
    StreamableHttpConnection,
    StreamableHttpConnectionFactory,
    _RpcRequest,
)


@pytest.mark.asyncio
async def test_runtime_http_error_is_propagated_to_pending_request(
    aiohttp_server,
) -> None:
    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        if payload["method"] == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                },
                headers={"Mcp-Session-Id": "test-session"},
            )
        if payload["method"] == "notifications/initialized":
            return web.Response(status=202)
        return web.json_response(
            {"error": "Access token expired, please re-authenticate"},
            status=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def handle_get(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)
        try:
            while True:
                await response.write(b": keepalive\n\n")
                await asyncio.sleep(0.05)
        except (asyncio.CancelledError, ConnectionResetError):
            return response

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    app.router.add_get("/mcp", handle_get)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping(
        {
            "server_url": server_url,
            "connect_timeout_seconds": "1",
            "read_timeout_seconds": "1",
        }
    )
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(bearer_token="expired-token")
        try:
            with anyio.fail_after(1):
                with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
                    await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_pending_request_receives_background_worker_error() -> None:
    request_sender, request_receiver = anyio.create_memory_object_stream(1)
    done_event = anyio.Event()
    request = httpx.Request("POST", "https://example.com/mcp")
    response = httpx.Response(401, request=request)
    worker_error = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=request,
        response=response,
    )
    connection = StreamableHttpConnection(
        request_sender=request_sender,
        done_event=done_event,
        worker_error_holder=[worker_error],
    )

    async def stop_worker_after_receiving_request() -> None:
        await request_receiver.receive()
        done_event.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(stop_worker_after_receiving_request)
        with anyio.fail_after(1):
            with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
                await connection.list_tools()
        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_worker_error_wins_over_request_cancellation() -> None:
    async def unused_caller(_) -> None:
        return None

    rpc_request = _RpcRequest(unused_caller)
    rpc_request.set_error(asyncio.CancelledError())
    done_event = anyio.Event()
    done_event.set()
    request = httpx.Request("POST", "https://example.com/mcp")
    response = httpx.Response(401, request=request)
    worker_error = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=request,
        response=response,
    )

    try:
        await rpc_request.wait(done_event, [worker_error])
    except BaseException as exc:
        assert exc is worker_error
    else:
        pytest.fail("Expected the worker error to be raised")


@pytest.mark.asyncio
async def test_closed_request_stream_waits_for_worker_error() -> None:
    request_sender, request_receiver = anyio.create_memory_object_stream(1)
    await request_receiver.aclose()
    done_event = anyio.Event()
    worker_error_holder: list[BaseException] = []
    request = httpx.Request("POST", "https://example.com/mcp")
    response = httpx.Response(401, request=request)
    worker_error = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=request,
        response=response,
    )
    connection = StreamableHttpConnection(
        request_sender=request_sender,
        done_event=done_event,
        worker_error_holder=worker_error_holder,
    )

    async def publish_worker_error() -> None:
        await anyio.sleep(0.01)
        worker_error_holder.append(worker_error)
        done_event.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(publish_worker_error)
        with anyio.fail_after(1):
            with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
                await connection.list_tools()
        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_unauthorized_request_refreshes_token_and_reconnects(
    aiohttp_server,
) -> None:
    initialize_tokens: list[str] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        authorization = request.headers["Authorization"]
        if payload["method"] == "initialize":
            initialize_tokens.append(authorization)
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                },
                headers={"Mcp-Session-Id": f"test-session-{len(initialize_tokens)}"},
            )
        if payload["method"] == "notifications/initialized":
            return web.Response(status=202)
        if authorization == "Bearer stale-token":
            return web.json_response(
                {"error": "Access token expired, please re-authenticate"},
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": []},
            }
        )

    async def handle_get(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)
        try:
            while True:
                await response.write(b": keepalive\n\n")
                await asyncio.sleep(0.05)
        except (asyncio.CancelledError, ConnectionResetError):
            return response

    class TokenProvider:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def get_token(self, *, force_refresh: bool = False) -> str:
            self.calls.append(force_refresh)
            return "fresh-token" if force_refresh else "stale-token"

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    app.router.add_get("/mcp", handle_get)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping(
        {
            "server_url": server_url,
            "connect_timeout_seconds": "1",
            "read_timeout_seconds": "1",
        }
    )
    factory = StreamableHttpConnectionFactory(config, server_url)
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
            with anyio.fail_after(2):
                result = await session.list_tools()
        finally:
            await session.aclose()
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert token_provider.calls == [False, True]
    assert initialize_tokens == ["Bearer stale-token", "Bearer fresh-token"]
