from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import types

from alibabacloud.mcp_proxy.auth.credential_tracker import CredentialRefreshError
from alibabacloud.mcp_proxy.config import RetrySettings
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


class FakeCredentialTracker:
    def __init__(self, generation: int = 1) -> None:
        self._generation = generation
        self.refresh_calls = 0
        self.fail_refresh = False

    async def refresh_if_stale(self) -> int:
        self.refresh_calls += 1
        if self.fail_refresh:
            raise CredentialRefreshError("profile cannot be resolved")
        return self._generation

    def current_generation(self) -> int:
        return self._generation

    def bump(self) -> None:
        self._generation += 1

    def get_client(self):
        return f"client-gen-{self._generation}"


@pytest.mark.asyncio
async def test_credential_refresh_failure_closes_and_rejects_old_connection() -> None:
    token_provider = FakeTokenProvider(["old-token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
    )

    await session.list_tools()
    old_connection = connection_factory.connections[0]
    tracker.fail_refresh = True

    with pytest.raises(UpstreamSessionError, match="previous identity"):
        await session.list_tools()

    assert old_connection.closed is True
    assert len(connection_factory.connections) == 1
    assert token_provider.calls == [False]


@pytest.mark.asyncio
async def test_identity_change_drops_and_rebuilds_connection() -> None:
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
    )

    await session.list_tools()  # builds connection at generation 1
    assert len(connection_factory.connections) == 1

    tracker.bump()  # simulate local credential switch
    await session.list_tools()  # must drop old + build new

    assert len(connection_factory.connections) == 2
    assert connection_factory.connections[0].closed is True
    assert tracker.refresh_calls == 2


@pytest.mark.asyncio
async def test_identity_change_rediscovers_factory_for_auto_url() -> None:
    """A credential switch re-runs discovery with the new client and swaps factory."""
    token_provider = FakeTokenProvider(["stable-token"])
    factory_a = FakeConnectionFactory(fail_first_connection=False)
    factory_b = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)

    resolved_clients: list[object] = []

    async def resolver(credential_client):
        resolved_clients.append(credential_client)
        return factory_b

    session = ReconnectingSession(
        factory_a,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
        factory_resolver=resolver,
    )

    await session.list_tools()  # builds connection via factory_a at generation 1
    assert len(factory_a.connections) == 1
    assert resolved_clients == []  # no re-discovery on first request

    tracker.bump()  # simulate cross-account credential switch -> generation 2
    await session.list_tools()  # must re-discover and connect via factory_b

    assert resolved_clients == ["client-gen-2"]  # discovery used the NEW client
    assert len(factory_b.connections) == 1
    assert factory_a.connections[0].closed is True
    assert len(factory_a.connections) == 1  # not reused after switch


@pytest.mark.asyncio
async def test_identity_change_fails_request_when_rediscovery_fails() -> None:
    """If re-discovery fails, the request must fail rather than reuse the old endpoint.

    The discovered URL is account/Core-scoped, so connecting via the previous
    identity's factory after a switch would send the new account's token to the
    old account's endpoint. The failing request must therefore raise, must NOT
    build a second connection on the old factory, and a later request only uses
    the new factory once discovery succeeds.
    """
    token_provider = FakeTokenProvider(["stable-token"])
    factory_a = FakeConnectionFactory(fail_first_connection=False)
    factory_b = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)

    attempts = {"n": 0}

    async def resolver(credential_client):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("discovery hiccup")
        return factory_b

    session = ReconnectingSession(
        factory_a,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
        factory_resolver=resolver,
    )

    await session.list_tools()  # builds connection via factory_a at generation 1
    assert len(factory_a.connections) == 1
    tracker.bump()  # cross-account switch -> generation 2

    # First request after the switch: discovery fails. The request must raise and
    # must NOT fall back to the old (previous-account) endpoint.
    with pytest.raises(UpstreamSessionError, match="re-discovery"):
        await session.list_tools()
    assert factory_b.connections == []  # new endpoint never resolved
    assert len(factory_a.connections) == 1  # old factory not reused for the new id
    assert factory_a.connections[0].closed is True  # stale connection dropped

    # A subsequent request retries discovery; only now is the new factory used.
    await session.list_tools()
    assert len(factory_b.connections) == 1
    assert len(factory_a.connections) == 1  # still never reused after the switch


@pytest.mark.asyncio
async def test_identity_refresh_discards_stale_factory_when_generation_advances() -> None:
    """A switch mid-discovery must not install a factory for a superseded identity.

    While discovery for generation 2 is in flight, the identity switches again to
    generation 3. The generation-2 endpoint is already stale, so it must be
    discarded and discovery re-run for generation 3 — the installed factory must
    match the newest identity, never an older one.
    """
    token_provider = FakeTokenProvider(["stable-token"])
    factory_a = FakeConnectionFactory(fail_first_connection=False)
    factory_gen2 = FakeConnectionFactory(fail_first_connection=False)
    factory_gen3 = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)

    resolved_for: list[str] = []

    async def resolver(credential_client):
        resolved_for.append(credential_client)
        if credential_client == "client-gen-2":
            # Simulate a second switch landing *during* this discovery.
            tracker.bump()  # -> generation 3
            return factory_gen2
        return factory_gen3

    session = ReconnectingSession(
        factory_a,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
        factory_resolver=resolver,
    )

    await session.list_tools()  # connection via factory_a at generation 1
    tracker.bump()  # -> generation 2

    await session.list_tools()

    # Discovery ran for gen2 (stale, discarded) then re-ran for gen3.
    assert resolved_for == ["client-gen-2", "client-gen-3"]
    # The generation-2 endpoint was never connected; only the newest one is used.
    assert factory_gen2.connections == []
    assert len(factory_gen3.connections) == 1


@pytest.mark.asyncio
async def test_credential_refresh_is_serialized_with_connection_build() -> None:
    """A concurrent request must not advance the tracker while another request is
    between selecting its token/factory and building the connection.

    ``refresh_if_stale`` -> factory alignment -> token acquisition -> connect must
    be one atomic transition under the session lock. Otherwise a second request's
    ``refresh_if_stale`` could bump the generation mid-flight, pairing a
    new-generation token with the previous identity's (account/Core-scoped)
    endpoint. Here request B must block until A has finished building its
    connection, so B cannot refresh the tracker while A is mid-connect.
    """
    connect_started = anyio.Event()
    finish_connect = anyio.Event()

    class GatedFactory:
        def __init__(self) -> None:
            self.connections: list[FakeConnection] = []
            self._gated_once = False

        async def connect(self, *, bearer_token: str) -> FakeConnection:
            if not self._gated_once:
                # First connection: hold the session lock open so a concurrent
                # request has a window to (wrongly) advance the tracker.
                self._gated_once = True
                connect_started.set()
                await finish_connect.wait()
            connection = FakeConnection()
            self.connections.append(connection)
            return connection

    token_provider = FakeTokenProvider(["stable-token"])
    factory = GatedFactory()
    tracker = FakeCredentialTracker(generation=1)
    session = ReconnectingSession(
        factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(session.list_tools)  # request A: blocks inside connect()
        await connect_started.wait()

        # A holds the session lock, suspended mid-connect, after refreshing once.
        assert tracker.refresh_calls == 1

        tg.start_soon(session.list_tools)  # request B
        await anyio.sleep(0.05)  # give B time to (try to) proceed

        # Because refresh is serialized under the connection lock, B is blocked
        # and cannot advance the tracker while A is still building its connection.
        assert tracker.refresh_calls == 1

        finish_connect.set()  # release A; B proceeds afterwards

    # B only refreshed after A released the lock, and reused A's connection since
    # the identity never actually changed.
    assert tracker.refresh_calls == 2
    assert len(factory.connections) == 1


@pytest.mark.asyncio
async def test_no_identity_change_reuses_connection_with_tracker() -> None:
    token_provider = FakeTokenProvider(["stable-token"])
    connection_factory = FakeConnectionFactory(fail_first_connection=False)
    tracker = FakeCredentialTracker(generation=1)
    session = ReconnectingSession(
        connection_factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
        credential_tracker=tracker,
    )

    await session.list_tools()
    await session.list_tools()

    assert len(connection_factory.connections) == 1  # reused, gen unchanged


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
