from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from mcp import Client, types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig
from alibabacloud.mcp_proxy.protocol import ProtocolMode
from alibabacloud.mcp_proxy.proxy.server import AlibabaCloudMcpProxyServer


@asynccontextmanager
async def proxy_memory_transport(
    server: Server,
) -> AsyncIterator[MessageStream]:
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                server.run,
                server_streams[0],
                server_streams[1],
                server.create_initialization_options(),
            )
            try:
                yield client_streams
            finally:
                task_group.cancel_scope.cancel()


class DownstreamRecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def list_prompts(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListPromptsResult:
        self.calls.append(("prompts/list", protocol_mode))
        return types.ListPromptsResult(prompts=[])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.GetPromptResult:
        self.calls.append(("prompts/get", name, arguments, protocol_mode))
        return types.GetPromptResult(messages=[])

    async def list_resources(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListResourcesResult:
        self.calls.append(("resources/list", protocol_mode))
        return types.ListResourcesResult(resources=[])

    async def read_resource(
        self,
        uri: AnyUrl,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ReadResourceResult:
        self.calls.append(("resources/read", str(uri), protocol_mode))
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=str(uri),
                    mimeType="text/plain",
                    text="resource",
                )
            ]
        )

    async def list_tools(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListToolsResult:
        self.calls.append(("tools/list", protocol_mode))
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="ExampleTool",
                    description="test",
                    inputSchema={"type": "object"},
                )
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.CallToolResult:
        self.calls.append(("tools/call", name, arguments, protocol_mode))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")]
        )

    async def aclose(self) -> None:
        self.calls.append(("close",))


def _proxy(
    session: DownstreamRecordingSession,
) -> AlibabaCloudMcpProxyServer:
    config = AlibabaCloudProxyConfig.from_mapping(
        {"server_url": "https://example.com/mcp"}
    )
    return AlibabaCloudMcpProxyServer(config, session)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_modern_auto_mode_discovers_tools_only() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="auto",
        cache=None,
    ) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_capabilities.tools is not None
        assert client.server_capabilities.prompts is None
        assert client.server_capabilities.resources is None
        result = await client.list_tools()

    assert result.result_type == "complete"
    assert [tool.name for tool in result.tools] == ["ExampleTool"]
    assert session.calls == [("tools/list", "2026-07-28")]


@pytest.mark.asyncio
async def test_modern_tools_list_can_be_first_request_without_discover() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="2026-07-28",
        cache=None,
    ) as client:
        result = await client.list_tools()

    assert result.result_type == "complete"
    assert session.calls == [("tools/list", "2026-07-28")]


@pytest.mark.asyncio
async def test_modern_tools_call_returns_complete_result() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="2026-07-28",
        cache=None,
    ) as client:
        await client.list_tools()
        session.calls.clear()
        result = await client.call_tool("ExampleTool", {"value": "ok"})

    assert result.result_type == "complete"
    assert result.content[0].text == "ok"  # type: ignore[union-attr]
    assert session.calls == [
        ("tools/call", "ExampleTool", {"value": "ok"}, "2026-07-28")
    ]


@pytest.mark.asyncio
async def test_legacy_initialize_advertises_existing_capabilities() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="legacy",
        cache=None,
    ) as client:
        assert client.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS
        assert client.server_capabilities.tools is not None
        assert client.server_capabilities.prompts is not None
        assert client.server_capabilities.resources is not None
        result = await client.list_tools()

    assert [tool.name for tool in result.tools] == ["ExampleTool"]
    assert session.calls == [("tools/list", "legacy")]


@pytest.mark.asyncio
async def test_modern_connection_rejects_late_initialize_without_upstream_call() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="2026-07-28",
        cache=None,
    ) as client:
        await client.list_tools()
        session.calls.clear()
        with pytest.raises(MCPError):
            await client.session.initialize()

    assert session.calls == []


@pytest.mark.asyncio
async def test_modern_wire_rejects_prompts_and_resources_without_upstream_call() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="2026-07-28",
        cache=None,
    ) as client:
        with pytest.raises(MCPError) as prompts_error:
            await client.session.list_prompts()
        with pytest.raises(MCPError) as resources_error:
            await client.session.list_resources()

    assert prompts_error.value.code == -32601
    assert resources_error.value.code == -32601
    assert session.calls == []


@pytest.mark.asyncio
async def test_legacy_wire_preserves_prompts_and_resources() -> None:
    session = DownstreamRecordingSession()
    proxy = _proxy(session)

    async with Client(
        proxy_memory_transport(proxy._server),  # noqa: SLF001
        mode="legacy",
        cache=None,
    ) as client:
        prompts = await client.list_prompts()
        resources = await client.list_resources()

    assert prompts.prompts == []
    assert resources.resources == []
    assert session.calls == [
        ("prompts/list", "legacy"),
        ("resources/list", "legacy"),
    ]
