from __future__ import annotations

import asyncio
import logging

import anyio
import httpx2
import pytest
from aiohttp import web
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig, RetrySettings
from alibabacloud.mcp_proxy.protocol import UnsupportedProtocolFeatureError
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
from alibabacloud.mcp_proxy.transport.upstream_http import (
    StreamableHttpConnection,
    StreamableHttpConnectionFactory,
    UpstreamHttpResponseError,
    _HttpAuditState,
    _RpcRequest,
)


def test_http_400_mcp_error_preserves_jsonrpc_semantics() -> None:
    state = _HttpAuditState(protocol_mode="2026-07-28")
    state.pending_error_status = 400
    original = MCPError(code=INVALID_PARAMS, message="Invalid params")

    result = state.wrap_error(original)

    assert result is original
    assert state.pending_error_status is None


def test_http_auth_error_still_preserves_status_for_token_refresh() -> None:
    state = _HttpAuditState(protocol_mode="2026-07-28")
    state.pending_error_status = 401
    original = MCPError(code=INVALID_PARAMS, message="Unauthorized")

    result = state.wrap_error(original)

    assert isinstance(result, UpstreamHttpResponseError)
    assert result.status_code == 401
    assert result.__cause__ is original


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
        connection = await factory.connect(
            bearer_token="expired-token",
            protocol_mode="legacy",
        )
        try:
            with anyio.fail_after(1):
                with pytest.raises(UpstreamHttpResponseError) as error:
                    await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_pending_request_receives_background_worker_error() -> None:
    request_sender, request_receiver = anyio.create_memory_object_stream(1)
    done_event = anyio.Event()
    request = httpx2.Request("POST", "https://example.com/mcp")
    response = httpx2.Response(401, request=request)
    worker_error = httpx2.HTTPStatusError(
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
            with pytest.raises(httpx2.HTTPStatusError, match="401 Unauthorized"):
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
    request = httpx2.Request("POST", "https://example.com/mcp")
    response = httpx2.Response(401, request=request)
    worker_error = httpx2.HTTPStatusError(
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
    request = httpx2.Request("POST", "https://example.com/mcp")
    response = httpx2.Response(401, request=request)
    worker_error = httpx2.HTTPStatusError(
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
            with pytest.raises(httpx2.HTTPStatusError, match="401 Unauthorized"):
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
                result = await session.list_tools(protocol_mode="legacy")
        finally:
            await session.aclose()
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert token_provider.calls == [False, True]
    assert initialize_tokens == ["Bearer stale-token", "Bearer fresh-token"]


@pytest.mark.asyncio
async def test_modern_list_tools_is_first_request_and_has_modern_envelope(
    aiohttp_server,
) -> None:
    received: list[dict[str, object]] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        received.append(
            {
                "method": payload["method"],
                "params": payload.get("params"),
                "protocol": request.headers.get("MCP-Protocol-Version"),
                "mcp_method": request.headers.get("Mcp-Method"),
                "session": request.headers.get("Mcp-Session-Id"),
            }
        )
        if payload["method"] == "tools/list":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "ExampleTool",
                                "inputSchema": {"type": "object"},
                            }
                        ],
                        "resultType": "complete",
                        "ttlMs": 0,
                        "cacheScope": "private",
                    },
                }
            )
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [],
                    "resultType": "complete",
                    "ttlMs": 0,
                    "cacheScope": "private",
                },
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="2026-07-28",
        )
        try:
            result = await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert result.result_type == "complete"
    assert [entry["method"] for entry in received] == ["tools/list"]
    assert received[0]["protocol"] == "2026-07-28"
    assert received[0]["mcp_method"] == "tools/list"
    assert received[0]["session"] is None
    params = received[0]["params"]
    assert isinstance(params, dict)
    meta = params["_meta"]
    assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert "io.modelcontextprotocol/clientInfo" in meta
    assert "io.modelcontextprotocol/clientCapabilities" in meta


@pytest.mark.asyncio
async def test_modern_call_tool_has_protocol_method_and_name_headers(
    aiohttp_server,
) -> None:
    received: list[dict[str, object]] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        received.append(
            {
                "method": payload["method"],
                "params": payload.get("params"),
                "protocol": request.headers.get("MCP-Protocol-Version"),
                "mcp_method": request.headers.get("Mcp-Method"),
                "mcp_name": request.headers.get("Mcp-Name"),
                "session": request.headers.get("Mcp-Session-Id"),
            }
        )
        if payload["method"] == "tools/list":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "ExampleTool",
                                "inputSchema": {"type": "object"},
                            }
                        ],
                        "resultType": "complete",
                        "ttlMs": 0,
                        "cacheScope": "private",
                    },
                }
            )
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "ok"}],
                    "resultType": "complete",
                },
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="2026-07-28",
        )
        try:
            await connection.list_tools()
            received.clear()
            result = await connection.call_tool("ExampleTool", {"value": "ok"})
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert result.result_type == "complete"
    assert [entry["method"] for entry in received] == ["tools/call"]
    assert received[0]["protocol"] == "2026-07-28"
    assert received[0]["mcp_method"] == "tools/call"
    assert received[0]["mcp_name"] == "ExampleTool"
    assert received[0]["session"] is None


@pytest.mark.asyncio
async def test_legacy_connection_preserves_initialize_and_session_order(
    aiohttp_server,
) -> None:
    received: list[tuple[str, str | None]] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        method = payload["method"]
        received.append((method, request.headers.get("Mcp-Session-Id")))
        if method == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                },
                headers={"Mcp-Session-Id": "legacy-session"},
            )
        if method == "notifications/initialized":
            return web.Response(status=202)
        if method == "tools/list":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"tools": []},
                }
            )
        raise AssertionError(f"Unexpected method: {method}")

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
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="legacy",
        )
        try:
            result = await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert received == [
        ("initialize", None),
        ("notifications/initialized", "legacy-session"),
        ("tools/list", "legacy-session"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_payload",
    [
        {"tools": [], "ttlMs": 0, "cacheScope": "private"},
        {"tools": [], "resultType": "complete", "ttlMs": 0},
    ],
)
async def test_modern_list_tools_rejects_missing_required_wire_fields(
    aiohttp_server,
    result_payload: dict[str, object],
) -> None:
    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": result_payload,
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="2026-07-28",
        )
        try:
            with pytest.raises(Exception, match="Field required"):
                await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_input_required_result_is_rejected_without_replaying_request(
    aiohttp_server,
) -> None:
    methods: list[str] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        methods.append(payload["method"])
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "resultType": "input_required",
                    "requestState": "opaque-state",
                },
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="2026-07-28",
        )
        try:
            with pytest.raises(
                UnsupportedProtocolFeatureError,
                match="multi-round requests are not supported",
            ):
                await connection.call_tool("ExampleTool", {})
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert methods == ["tools/call"]


@pytest.mark.asyncio
async def test_is_error_tool_result_is_returned_without_reconnect(
    aiohttp_server,
) -> None:
    methods: list[str] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        methods.append(payload["method"])
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [],
                    "isError": True,
                    "resultType": "complete",
                },
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="2026-07-28",
        )
        try:
            result = await connection.call_tool("ExampleTool", {})
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert result.is_error is True
    assert methods == ["tools/call"]


@pytest.mark.asyncio
async def test_modern_401_refreshes_token_without_probe_or_fallback(
    aiohttp_server,
) -> None:
    requests: list[tuple[str, str]] = []

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        authorization = request.headers["Authorization"]
        requests.append((payload["method"], authorization))
        if authorization == "Bearer stale-token":
            return web.json_response({"error": "expired"}, status=401)
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [],
                    "resultType": "complete",
                    "ttlMs": 0,
                    "cacheScope": "private",
                },
            }
        )

    class TokenProvider:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def get_token(self, *, force_refresh: bool = False) -> str:
            self.calls.append(force_refresh)
            return "fresh-token" if force_refresh else "stale-token"

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
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
            result = await session.list_tools(protocol_mode="2026-07-28")
        finally:
            await session.aclose()
            task_group.cancel_scope.cancel()

    assert result.tools == []
    assert token_provider.calls == [False, True]
    assert requests == [
        ("tools/list", "Bearer stale-token"),
        ("tools/list", "Bearer fresh-token"),
    ]


@pytest.mark.asyncio
async def test_legacy_response_hook_writes_session_marker_once(
    aiohttp_server,
    monkeypatch,
) -> None:
    marker_calls: list[str] = []
    monkeypatch.setattr(
        "alibabacloud.mcp_proxy.transport.upstream_http.write_mcp_session_marker",
        marker_calls.append,
    )

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        method = payload["method"]
        headers = {"Mcp-Session-Id": "legacy-session"}
        if method == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"},
                    },
                },
                headers=headers,
            )
        if method == "notifications/initialized":
            return web.Response(status=202, headers=headers)
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": []},
            },
            headers=headers,
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
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="test-token",
            protocol_mode="legacy",
        )
        try:
            await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert marker_calls == ["legacy-session"]


@pytest.mark.asyncio
async def test_modern_response_never_writes_session_marker(
    aiohttp_server,
    monkeypatch,
) -> None:
    marker_calls: list[str] = []
    monkeypatch.setattr(
        "alibabacloud.mcp_proxy.transport.upstream_http.write_mcp_session_marker",
        marker_calls.append,
    )

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [],
                    "resultType": "complete",
                    "ttlMs": 0,
                    "cacheScope": "private",
                },
            },
            headers={"Mcp-Session-Id": "must-not-be-marked"},
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="secret-token-value",
            protocol_mode="2026-07-28",
        )
        try:
            await connection.list_tools()
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert marker_calls == []


@pytest.mark.asyncio
async def test_http_audit_logs_only_redacted_protocol_metadata(
    aiohttp_server,
    caplog,
) -> None:
    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [],
                    "isError": True,
                    "resultType": "complete",
                },
            }
        )

    app = web.Application()
    app.router.add_post("/mcp", handle_post)
    server = await aiohttp_server(app)
    server_url = str(server.make_url("/mcp"))
    config = AlibabaCloudProxyConfig.from_mapping({"server_url": server_url})
    factory = StreamableHttpConnectionFactory(config, server_url)
    caplog.set_level(
        logging.DEBUG,
        logger="alibabacloud.mcp_proxy.transport.upstream_http",
    )

    async with anyio.create_task_group() as task_group:
        factory.set_task_group(task_group)
        connection = await factory.connect(
            bearer_token="secret-token-value",
            protocol_mode="2026-07-28",
        )
        try:
            await connection.call_tool(
                "SensitiveToolName",
                {"value": "secret-tool-argument"},
            )
        finally:
            await connection.close()
            task_group.cancel_scope.cancel()

    assert "transport=streamable-http" in caplog.text
    assert "protocol_mode=2026-07-28" in caplog.text
    assert "method=tools/call" in caplog.text
    assert "status=200" in caplog.text
    assert "session_header_present=False" in caplog.text
    assert "secret-token-value" not in caplog.text
    assert "secret-tool-argument" not in caplog.text
    assert "SensitiveToolName" not in caplog.text
