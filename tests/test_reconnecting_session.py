from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import types
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

from alibabacloud.mcp_proxy.config import RetrySettings
from alibabacloud.mcp_proxy.protocol import (
    MODERN_PROTOCOL_MODE,
    ProtocolMode,
    ProtocolModeMismatchError,
    UnsupportedProtocolFeatureError,
)
from alibabacloud.mcp_proxy.session.reconnecting_session import (
    ReconnectingSession,
    UpstreamSessionError,
)
from alibabacloud.mcp_proxy.transport.http_client import ProxyDependencyError


class FakeTokenProvider:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.calls: list[bool] = []

    async def get_token(self, *, force_refresh: bool = False) -> str:
        self.calls.append(force_refresh)
        index = min(len(self.calls) - 1, len(self.tokens) - 1)
        return self.tokens[index]


class FakeConnection:
    def __init__(
        self,
        *,
        fail_once: bool = False,
        permanent_error: bool = False,
        tool_error_result: bool = False,
        mcp_error_code: int | None = None,
    ) -> None:
        self.fail_once = fail_once
        self.permanent_error = permanent_error
        self.tool_error_result = tool_error_result
        self.mcp_error_code = mcp_error_code
        self.closed = False
        self.calls = 0

    async def list_tools(self) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError("401 token expired")
        if self.permanent_error:
            raise UnsupportedProtocolFeatureError("input_required is not supported")
        if self.mcp_error_code is not None:
            raise MCPError(
                code=self.mcp_error_code,
                message="MCP request failed",
            )
        if self.tool_error_result:
            return types.CallToolResult(content=[], isError=True)
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"{name}:{(arguments or {}).get('message', '')}",
                )
            ]
        )

    async def close(self) -> None:
        self.closed = True


class FakeConnectionFactory:
    def __init__(
        self,
        *,
        fail_first_connection: bool = True,
        permanent_error: bool = False,
        tool_error_result: bool = False,
        mcp_error_code: int | None = None,
    ) -> None:
        self.fail_first_connection = fail_first_connection
        self.permanent_error = permanent_error
        self.tool_error_result = tool_error_result
        self.mcp_error_code = mcp_error_code
        self.connections: list[FakeConnection] = []
        self.connect_calls: list[tuple[str, ProtocolMode]] = []

    async def connect(
        self,
        *,
        bearer_token: str,
        protocol_mode: ProtocolMode,
    ) -> FakeConnection:
        self.connect_calls.append((bearer_token, protocol_mode))
        connection = FakeConnection(
            fail_once=self.fail_first_connection and len(self.connections) == 0,
            permanent_error=self.permanent_error,
            tool_error_result=self.tool_error_result,
            mcp_error_code=self.mcp_error_code,
        )
        self.connections.append(connection)
        return connection


class MissingSocksConnectionFactory:
    def __init__(self) -> None:
        self.calls = 0

    async def connect(
        self,
        *,
        bearer_token: str,
        protocol_mode: ProtocolMode,
    ) -> FakeConnection:
        self.calls += 1
        raise ProxyDependencyError("SOCKS support is unavailable; install httpx2[socks]")


@pytest.mark.asyncio
async def test_proxy_dependency_error_is_not_retried_or_wrapped() -> None:
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = MissingSocksConnectionFactory()
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    with pytest.raises(ProxyDependencyError, match=r"install httpx2\[socks\]"):
        await session.list_tools(protocol_mode="legacy")

    assert connection_factory.calls == 1
    assert token_provider.calls == [False]


@pytest.mark.asyncio
async def test_reconnecting_session_retries_with_fresh_token() -> None:
    token_provider = FakeTokenProvider(["stale-token", "fresh-token"])
    connection_factory = FakeConnectionFactory()
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=2, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    result = await session.call_tool(
        "echo",
        {"message": "hello"},
        protocol_mode=MODERN_PROTOCOL_MODE,
    )

    assert connection_factory.connect_calls == [
        ("stale-token", MODERN_PROTOCOL_MODE),
        ("fresh-token", MODERN_PROTOCOL_MODE),
    ]
    assert token_provider.calls == [False, True]
    assert result.content[0].text == "echo:hello"
    assert connection_factory.connections[0].closed is True


@pytest.mark.asyncio
async def test_reconnecting_session_reuses_live_connection() -> None:
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    await session.list_tools(protocol_mode="legacy")
    await session.call_tool("echo", {"message": "hello"}, protocol_mode="legacy")

    assert connection_factory.connect_calls == [("stable-token", "legacy")]
    assert len(connection_factory.connections) == 1


@pytest.mark.asyncio
async def test_reconnecting_session_applies_tool_policy_without_safety_policy(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str | None, tuple[str, ...]]] = []

    async def fake_apply_safety_policy(
        bearer_token: str,
        safety_policy: str | None,
        *,
        allowed_tools: tuple[str, ...] = (),
    ) -> None:
        calls.append((bearer_token, safety_policy, tuple(allowed_tools)))

    monkeypatch.setattr(
        "alibabacloud.mcp_proxy.session.reconnecting_session.apply_safety_policy",
        fake_apply_safety_policy,
    )
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        allowed_tools=("AlibabaCloud___RunScript", "AlibabaCloud___GetTask"),
    )

    await session.list_tools(protocol_mode="legacy")

    assert calls == [
        (
            "stable-token",
            None,
            ("AlibabaCloud___RunScript", "AlibabaCloud___GetTask"),
        )
    ]


@pytest.mark.asyncio
async def test_first_request_binds_protocol_mode_and_passes_it_to_factory() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert connection_factory.connect_calls == [("token", MODERN_PROTOCOL_MODE)]


@pytest.mark.asyncio
async def test_reconnect_preserves_bound_protocol_mode() -> None:
    token_provider = FakeTokenProvider(["stale-token", "fresh-token"])
    connection_factory = FakeConnectionFactory()
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=2, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    await session.call_tool("echo", {}, protocol_mode=MODERN_PROTOCOL_MODE)

    assert connection_factory.connect_calls == [
        ("stale-token", MODERN_PROTOCOL_MODE),
        ("fresh-token", MODERN_PROTOCOL_MODE),
    ]


@pytest.mark.asyncio
async def test_protocol_mode_mismatch_is_rejected_without_token_or_reconnect() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    await session.list_tools(protocol_mode="legacy")

    with pytest.raises(ProtocolModeMismatchError, match="already bound"):
        await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert token_provider.calls == [False]
    assert connection_factory.connect_calls == [("token", "legacy")]
    assert connection_factory.connections[0].closed is False


@pytest.mark.asyncio
async def test_aclose_clears_protocol_mode_binding() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    await session.list_tools(protocol_mode="legacy")
    await session.aclose()
    await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert connection_factory.connect_calls == [
        ("token", "legacy"),
        ("token", MODERN_PROTOCOL_MODE),
    ]


@pytest.mark.asyncio
async def test_non_retryable_proxy_error_is_not_retried_or_wrapped() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(
        fail_first_connection=False,
        permanent_error=True,
    )
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    with pytest.raises(UnsupportedProtocolFeatureError, match="input_required"):
        await session.call_tool("example", {}, protocol_mode=MODERN_PROTOCOL_MODE)

    assert token_provider.calls == [False]
    assert connection_factory.connect_calls == [("token", MODERN_PROTOCOL_MODE)]
    assert connection_factory.connections[0].closed is False


@pytest.mark.asyncio
async def test_tool_error_result_is_returned_without_retry() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(
        fail_first_connection=False,
        tool_error_result=True,
    )
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    result = await session.call_tool(
        "example",
        {},
        protocol_mode=MODERN_PROTOCOL_MODE,
    )

    assert result.is_error is True
    assert connection_factory.connect_calls == [("token", MODERN_PROTOCOL_MODE)]


@pytest.mark.asyncio
async def test_mcp_error_is_preserved_without_retry() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(
        fail_first_connection=False,
        mcp_error_code=INVALID_PARAMS,
    )
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(
            max_attempts=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.01,
        ),
    )

    with pytest.raises(MCPError) as error:
        await session.call_tool(
            "missing",
            {},
            protocol_mode=MODERN_PROTOCOL_MODE,
        )

    assert error.value.code == INVALID_PARAMS
    assert error.value.message == "MCP request failed"
    assert token_provider.calls == [False]
    assert connection_factory.connect_calls == [
        ("token", MODERN_PROTOCOL_MODE),
    ]
    assert connection_factory.connections[0].calls == 1
    assert connection_factory.connections[0].closed is False


@pytest.mark.asyncio
async def test_internal_mcp_error_retains_legacy_retry_behavior() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(
        fail_first_connection=False,
        mcp_error_code=INTERNAL_ERROR,
    )
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(
            max_attempts=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.01,
        ),
    )

    with pytest.raises(
        UpstreamSessionError,
        match="failed after 3 attempts",
    ):
        await session.call_tool(
            "transient",
            {},
            protocol_mode=MODERN_PROTOCOL_MODE,
        )

    assert token_provider.calls == [False, False, False]
    assert len(connection_factory.connect_calls) == 3
    assert [connection.calls for connection in connection_factory.connections] == [
        1,
        1,
        1,
    ]
    assert all(
        connection.closed
        for connection in connection_factory.connections
    )


@pytest.mark.asyncio
async def test_concurrent_same_era_requests_share_one_connection() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    results: list[types.ListToolsResult] = []

    async def list_tools() -> None:
        results.append(
            await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)
        )

    async with anyio.create_task_group() as task_group:
        for _ in range(10):
            task_group.start_soon(list_tools)

    assert len(results) == 10
    assert connection_factory.connect_calls == [
        ("token", MODERN_PROTOCOL_MODE)
    ]
    assert len(connection_factory.connections) == 1


@pytest.mark.asyncio
async def test_concurrent_mixed_era_requests_never_create_two_era_connections() -> None:
    token_provider = FakeTokenProvider(["token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    outcomes: list[tuple[ProtocolMode, str]] = []

    async def list_tools(protocol_mode: ProtocolMode) -> None:
        try:
            await session.list_tools(protocol_mode=protocol_mode)
        except ProtocolModeMismatchError:
            outcomes.append((protocol_mode, "rejected"))
        else:
            outcomes.append((protocol_mode, "complete"))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(list_tools, "legacy")
        task_group.start_soon(list_tools, MODERN_PROTOCOL_MODE)

    assert sorted(status for _, status in outcomes) == ["complete", "rejected"]
    assert len(connection_factory.connect_calls) == 1
    connected_mode = connection_factory.connect_calls[0][1]
    assert outcomes == [
        (connected_mode, "complete"),
        (
            MODERN_PROTOCOL_MODE
            if connected_mode == "legacy"
            else "legacy",
            "rejected",
        ),
    ]
