from __future__ import annotations

import logging
from typing import Any

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, METHOD_NOT_FOUND
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig
from alibabacloud.mcp_proxy.protocol import (
    MODERN_PROTOCOL_MODE,
    ProtocolMode,
    to_upstream_protocol_mode,
)
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
from alibabacloud.mcp_proxy.transport.stdio_server import run_stdio_server

_LOGGER = logging.getLogger(__name__)


class AlibabaCloudMcpProxyServer:
    def __init__(
        self,
        config: AlibabaCloudProxyConfig,
        session: ReconnectingSession,
    ) -> None:
        self._config = config
        self._session = session
        self._server = Server(
            "alibabacloud-mcp-proxy",
            on_list_prompts=self._handle_list_prompts,
            on_get_prompt=self._handle_get_prompt,
            on_list_resources=self._handle_list_resources,
            on_read_resource=self._handle_read_resource,
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
        )
        self._server.add_request_handler(
            "server/discover",
            types.RequestParams,
            self._handle_discover,
        )

    async def run(self) -> None:
        await run_stdio_server(self._server)

    async def aclose(self) -> None:
        await self._session.aclose()

    async def _handle_discover(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.RequestParams,
    ) -> types.DiscoverResult:
        del ctx, params
        return types.DiscoverResult(
            supportedVersions=list(MODERN_PROTOCOL_VERSIONS),
            capabilities=types.ServerCapabilities(
                tools=types.ToolsCapability(),
            ),
        )

    async def _handle_list_prompts(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        del params
        protocol_mode = self._require_legacy(ctx)
        try:
            return await self._session.list_prompts(protocol_mode=protocol_mode)
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error("Upstream prompts/list failed: %s", exc, exc_info=True)
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    async def _handle_get_prompt(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.GetPromptRequestParams,
    ) -> types.GetPromptResult:
        protocol_mode = self._require_legacy(ctx)
        try:
            return await self._session.get_prompt(
                params.name,
                params.arguments,
                protocol_mode=protocol_mode,
            )
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Upstream prompts/get:%s failed: %s",
                params.name,
                exc,
                exc_info=True,
            )
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    async def _handle_list_resources(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        del params
        protocol_mode = self._require_legacy(ctx)
        try:
            return await self._session.list_resources(protocol_mode=protocol_mode)
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error("Upstream resources/list failed: %s", exc, exc_info=True)
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    async def _handle_read_resource(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        protocol_mode = self._require_legacy(ctx)
        uri = AnyUrl(params.uri)
        try:
            return await self._session.read_resource(
                uri,
                protocol_mode=protocol_mode,
            )
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Upstream resources/read:%s failed: %s",
                uri,
                exc,
                exc_info=True,
            )
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    async def _handle_list_tools(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        del params
        protocol_mode = to_upstream_protocol_mode(ctx.protocol_version)
        try:
            return await self._session.list_tools(protocol_mode=protocol_mode)
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error("Upstream tools/list failed: %s", exc, exc_info=True)
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    async def _handle_call_tool(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        protocol_mode = to_upstream_protocol_mode(ctx.protocol_version)
        try:
            return await self._session.call_tool(
                params.name,
                params.arguments,
                protocol_mode=protocol_mode,
            )
        except MCPError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Upstream tools/call:%s failed: %s",
                params.name,
                exc,
                exc_info=True,
            )
            raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc

    @staticmethod
    def _require_legacy(
        ctx: ServerRequestContext[Any, Any],
    ) -> ProtocolMode:
        protocol_mode = to_upstream_protocol_mode(ctx.protocol_version)
        if protocol_mode == MODERN_PROTOCOL_MODE:
            raise MCPError(
                code=METHOD_NOT_FOUND,
                message="Method not found",
            )
        return protocol_mode
