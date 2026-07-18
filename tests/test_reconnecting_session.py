from __future__ import annotations

from typing import Any

import pytest
from mcp import types

from alibabacloud.mcp_proxy.config import RetrySettings
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
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
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
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
    def __init__(self, *, fail_first_connection: bool = True) -> None:
        self.fail_first_connection = fail_first_connection
        self.connections: list[FakeConnection] = []
        self.tokens: list[str] = []

    async def connect(self, *, bearer_token: str) -> FakeConnection:
        self.tokens.append(bearer_token)
        connection = FakeConnection(
            fail_once=self.fail_first_connection and len(self.connections) == 0
        )
        self.connections.append(connection)
        return connection


class MissingSocksConnectionFactory:
    def __init__(self) -> None:
        self.calls = 0

    async def connect(self, *, bearer_token: str) -> FakeConnection:
        self.calls += 1
        raise ProxyDependencyError("SOCKS support is unavailable; install httpx[socks]")


@pytest.mark.asyncio
async def test_proxy_dependency_error_is_not_retried_or_wrapped() -> None:
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = MissingSocksConnectionFactory()
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    with pytest.raises(ProxyDependencyError, match=r"install httpx\[socks\]"):
        await session.list_tools()

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

    result = await session.call_tool("echo", {"message": "hello"})

    assert connection_factory.tokens == ["stale-token", "fresh-token"]
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

    await session.list_tools()
    await session.call_tool("echo", {"message": "hello"})

    assert connection_factory.tokens == ["stable-token"]
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

    await session.list_tools()

    assert calls == [
        (
            "stable-token",
            None,
            ("AlibabaCloud___RunScript", "AlibabaCloud___GetTask"),
        )
    ]
