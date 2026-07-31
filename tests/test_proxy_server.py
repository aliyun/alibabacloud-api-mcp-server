from __future__ import annotations

from typing import Any

import pytest
from mcp import types
from mcp.server import ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, METHOD_NOT_FOUND
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig
from alibabacloud.mcp_proxy.protocol import ProtocolMode
from alibabacloud.mcp_proxy.proxy.server import AlibabaCloudMcpProxyServer


def _context(
    protocol_version: str,
    method: str,
) -> ServerRequestContext[Any, Any]:
    return ServerRequestContext(
        session=object(),  # type: ignore[arg-type]
        lifespan_context=None,
        protocol_version=protocol_version,
        method=method,
    )


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error: BaseException | None = None
        self.resource_result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///text",
                    mimeType="text/plain",
                    text="hello",
                ),
                types.BlobResourceContents(
                    uri="file:///blob",
                    mimeType="application/octet-stream",
                    blob="AQI=",
                ),
            ]
        )

    def _raise_if_needed(self) -> None:
        if self.error is not None:
            raise self.error

    async def list_prompts(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListPromptsResult:
        self.calls.append(("prompts/list", protocol_mode))
        self._raise_if_needed()
        return types.ListPromptsResult(prompts=[])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.GetPromptResult:
        self.calls.append(("prompts/get", name, arguments, protocol_mode))
        self._raise_if_needed()
        return types.GetPromptResult(messages=[])

    async def list_resources(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListResourcesResult:
        self.calls.append(("resources/list", protocol_mode))
        self._raise_if_needed()
        return types.ListResourcesResult(resources=[])

    async def read_resource(
        self,
        uri: AnyUrl,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ReadResourceResult:
        self.calls.append(("resources/read", str(uri), protocol_mode))
        self._raise_if_needed()
        return self.resource_result

    async def list_tools(
        self,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.ListToolsResult:
        self.calls.append(("tools/list", protocol_mode))
        self._raise_if_needed()
        return types.ListToolsResult(tools=[])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        *,
        protocol_mode: ProtocolMode,
    ) -> types.CallToolResult:
        self.calls.append(("tools/call", name, arguments, protocol_mode))
        self._raise_if_needed()
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")]
        )

    async def aclose(self) -> None:
        self.calls.append(("close",))


def _proxy(session: RecordingSession) -> AlibabaCloudMcpProxyServer:
    config = AlibabaCloudProxyConfig.from_mapping(
        {"server_url": "https://example.com/mcp"}
    )
    return AlibabaCloudMcpProxyServer(config, session)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_discover_advertises_only_tools_without_accessing_session() -> None:
    session = RecordingSession()
    proxy = _proxy(session)

    result = await proxy._handle_discover(  # noqa: SLF001
        _context("2026-07-28", "server/discover"),
        types.RequestParams(),
    )

    assert result.supported_versions == list(MODERN_PROTOCOL_VERSIONS)
    assert result.capabilities.tools is not None
    assert result.capabilities.prompts is None
    assert result.capabilities.resources is None
    assert result.result_type == "complete"
    assert session.calls == []


@pytest.mark.asyncio
async def test_list_tools_forwards_modern_protocol_mode() -> None:
    session = RecordingSession()
    proxy = _proxy(session)

    result = await proxy._handle_list_tools(  # noqa: SLF001
        _context("2026-07-28", "tools/list"),
        None,
    )

    assert result.tools == []
    assert session.calls == [("tools/list", "2026-07-28")]


@pytest.mark.asyncio
async def test_call_tool_forwards_legacy_protocol_mode_and_typed_params() -> None:
    session = RecordingSession()
    proxy = _proxy(session)

    result = await proxy._handle_call_tool(  # noqa: SLF001
        _context("2025-11-25", "tools/call"),
        types.CallToolRequestParams(
            name="ExampleTool",
            arguments={"value": "ok"},
        ),
    )

    assert result.content[0].text == "ok"  # type: ignore[union-attr]
    assert session.calls == [
        ("tools/call", "ExampleTool", {"value": "ok"}, "legacy")
    ]


@pytest.mark.asyncio
async def test_modern_prompts_and_resources_are_rejected_without_upstream_call() -> None:
    session = RecordingSession()
    proxy = _proxy(session)
    ctx = _context("2026-07-28", "prompts/list")

    with pytest.raises(MCPError) as prompts_error:
        await proxy._handle_list_prompts(ctx, None)  # noqa: SLF001
    with pytest.raises(MCPError) as prompt_error:
        await proxy._handle_get_prompt(  # noqa: SLF001
            _context("2026-07-28", "prompts/get"),
            types.GetPromptRequestParams(name="prompt"),
        )
    with pytest.raises(MCPError) as resources_error:
        await proxy._handle_list_resources(  # noqa: SLF001
            _context("2026-07-28", "resources/list"),
            None,
        )
    with pytest.raises(MCPError) as resource_error:
        await proxy._handle_read_resource(  # noqa: SLF001
            _context("2026-07-28", "resources/read"),
            types.ReadResourceRequestParams(uri="file:///resource"),
        )

    assert {
        prompts_error.value.code,
        prompt_error.value.code,
        resources_error.value.code,
        resource_error.value.code,
    } == {METHOD_NOT_FOUND}
    assert session.calls == []


@pytest.mark.asyncio
async def test_handler_preserves_mcp_error() -> None:
    session = RecordingSession()
    original = MCPError(code=METHOD_NOT_FOUND, message="upstream method missing")
    session.error = original
    proxy = _proxy(session)

    with pytest.raises(MCPError) as error:
        await proxy._handle_list_tools(  # noqa: SLF001
            _context("2025-11-25", "tools/list"),
            None,
        )

    assert error.value is original


@pytest.mark.asyncio
async def test_handler_wraps_unexpected_error_as_internal_error() -> None:
    session = RecordingSession()
    session.error = RuntimeError("upstream exploded")
    proxy = _proxy(session)

    with pytest.raises(MCPError) as error:
        await proxy._handle_list_tools(  # noqa: SLF001
            _context("2026-07-28", "tools/list"),
            None,
        )

    assert error.value.code == INTERNAL_ERROR
    assert error.value.message == "upstream exploded"


@pytest.mark.asyncio
async def test_read_resource_returns_text_and_blob_contents_unchanged() -> None:
    session = RecordingSession()
    proxy = _proxy(session)

    result = await proxy._handle_read_resource(  # noqa: SLF001
        _context("2025-11-25", "resources/read"),
        types.ReadResourceRequestParams(uri="file:///resource"),
    )

    assert result is session.resource_result
    assert result.contents[0].text == "hello"  # type: ignore[union-attr]
    assert result.contents[1].blob == "AQI="  # type: ignore[union-attr]
    assert session.calls == [
        ("resources/read", "file:///resource", "legacy")
    ]
