from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import anyio
from mcp import types
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.auth.credential_tracker import CredentialRefreshError
from alibabacloud.mcp_proxy.auth.token_provider import CachedBearerTokenProvider
from alibabacloud.mcp_proxy.config import RetrySettings
from alibabacloud.mcp_proxy.safety_policy import apply_safety_policy
from alibabacloud.mcp_proxy.transport.http_client import ProxyDependencyError

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class UpstreamConnection(Protocol):
    async def list_prompts(self) -> types.ListPromptsResult:
        ...

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        ...

    async def list_resources(self) -> types.ListResourcesResult:
        ...

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        ...

    async def list_tools(self) -> types.ListToolsResult:
        ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        ...

    async def close(self) -> None:
        ...


class UpstreamConnectionFactory(Protocol):
    async def connect(self, *, bearer_token: str) -> UpstreamConnection:
        ...


class UpstreamSessionError(RuntimeError):
    """Raised when the proxy cannot complete an upstream call after retries."""


@dataclass(slots=True, frozen=True)
class RetryState:
    attempt: int
    delay_seconds: float


class ReconnectingSession:
    def __init__(
        self,
        connection_factory: UpstreamConnectionFactory,
        token_provider: CachedBearerTokenProvider,
        retry_settings: RetrySettings,
        *,
        safety_policy: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        credential_tracker: Any = None,
        factory_resolver: Callable[[Any], Awaitable[UpstreamConnectionFactory]]
        | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._token_provider = token_provider
        self._retry_settings = retry_settings
        self._safety_policy = safety_policy
        self._allowed_tools = tuple(allowed_tools or ())
        self._credential_tracker = credential_tracker
        self._factory_resolver = factory_resolver
        self._connection: UpstreamConnection | None = None
        self._connection_generation = 0
        # The initial factory was built with the credentials current at startup,
        # so it starts aligned with the tracker's current generation. This avoids
        # a spurious re-discovery on the very first request.
        self._factory_generation = (
            credential_tracker.current_generation()
            if credential_tracker is not None
            else 0
        )
        self._policy_applied_for_token: str | None = None
        self._lock = anyio.Lock()
        # Serializes endpoint re-discovery so concurrent requests cannot run
        # overlapping discoveries and install factories out of generation order.
        self._identity_refresh_lock = anyio.Lock()

    async def list_tools(self) -> types.ListToolsResult:
        return await self._run_with_retries("tools/list", lambda conn: conn.list_tools())

    async def list_prompts(self) -> types.ListPromptsResult:
        return await self._run_with_retries("prompts/list", lambda conn: conn.list_prompts())

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        return await self._run_with_retries(
            f"prompts/get:{name}",
            lambda conn: conn.get_prompt(name, arguments),
        )

    async def list_resources(self) -> types.ListResourcesResult:
        return await self._run_with_retries(
            "resources/list",
            lambda conn: conn.list_resources(),
        )

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        return await self._run_with_retries(
            f"resources/read:{uri}",
            lambda conn: conn.read_resource(uri),
        )

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        return await self._run_with_retries(
            f"tools/call:{name}",
            lambda conn: conn.call_tool(name, arguments),
        )

    async def aclose(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _run_with_retries(
        self,
        operation_name: str,
        callback: Callable[[UpstreamConnection], Awaitable[T]],
    ) -> T:
        last_error: Exception | None = None

        for retry_state in self._retry_states():
            # Alignment phase. This inner loop re-runs endpoint discovery (a
            # network call made *outside* ``_lock``) until the factory matches the
            # current identity. Re-discovery does NOT consume a retry attempt: a
            # cross-account switch must still get one real connection attempt.
            while True:
                connections_to_close: list[UpstreamConnection] = []
                need_rediscovery = False
                call_succeeded = False
                call_result: T | None = None
                dependency_error: ProxyDependencyError | None = None
                credential_refresh_error: CredentialRefreshError | None = None

                async with self._lock:
                    # Refresh the tracker and align the factory *inside* ``_lock``.
                    # The tracker generation only advances via ``refresh_if_stale``,
                    # so holding the lock across refresh -> alignment -> token ->
                    # connect makes the whole transition atomic: no concurrent
                    # request can advance the generation between the token being
                    # minted and the connection being built, which would otherwise
                    # send a new identity's token through the old endpoint.
                    if self._credential_tracker is not None:
                        try:
                            await self._credential_tracker.refresh_if_stale()
                        except CredentialRefreshError as exc:
                            credential_refresh_error = exc
                            if self._connection is not None:
                                connections_to_close.append(self._connection)
                                self._connection = None
                        else:
                            generation = self._credential_tracker.current_generation()
                            if (
                                self._connection is not None
                                and self._connection_generation != generation
                            ):
                                # Detach a connection built for a previous identity;
                                # close it outside the lock (SSE cancel-scope rules).
                                connections_to_close.append(self._connection)
                                self._connection = None
                            if self._factory_generation != generation:
                                if self._factory_resolver is None:
                                    # A fixed (explicit-URL) factory is valid for every
                                    # identity; just advance the marker.
                                    self._factory_generation = generation
                                else:
                                    need_rediscovery = True

                    if credential_refresh_error is None and not need_rediscovery:
                        force_refresh = (
                            retry_state.attempt > 0 and _should_force_refresh(last_error)
                        )
                        token = await self._token_provider.get_token(
                            force_refresh=force_refresh
                        )
                        try:
                            connection = await self._ensure_connection_locked(token)
                            call_result = await callback(connection)
                            call_succeeded = True
                        except ProxyDependencyError as exc:
                            # A missing local dependency cannot be fixed by
                            # reconnecting. Preserve the actionable error instead of
                            # obscuring it behind the generic "failed after N" wrap.
                            dependency_error = exc
                        except Exception as exc:  # pragma: no cover - upstream SDK
                            last_error = exc
                            LOGGER.warning(
                                "Upstream %s failed on attempt %s/%s: %s",
                                operation_name,
                                retry_state.attempt + 1,
                                self._retry_settings.max_attempts,
                                exc,
                            )
                            # Detach but do NOT close inside the lock / handler:
                            # closing SSE connections here would trigger cancel-scope
                            # nesting violations.
                            if self._connection is not None:
                                connections_to_close.append(self._connection)
                                self._connection = None

                # Close detached connections *outside* the lock so the cancel-scope
                # stack is clean.
                for connection in connections_to_close:
                    try:
                        await connection.close()
                    except Exception:
                        LOGGER.debug(
                            "Error closing detached connection (ignored)",
                            exc_info=True,
                        )

                if dependency_error is not None:
                    raise dependency_error
                if credential_refresh_error is not None:
                    raise UpstreamSessionError(
                        "Local credential refresh failed; the previous identity "
                        "will not be reused."
                    ) from credential_refresh_error
                if call_succeeded:
                    return call_result  # type: ignore[return-value]

                if need_rediscovery:
                    # Re-discover the endpoint for the new identity (outside the
                    # lock), then loop to re-check under the lock and connect.
                    await self._rediscover_factory()
                    if (
                        self._factory_generation
                        != self._credential_tracker.current_generation()
                    ):
                        # Discovery could not align the factory with the current
                        # identity (it failed). Never fall back to the previous
                        # identity's endpoint: fail now; a later request retries.
                        raise UpstreamSessionError(
                            "Upstream endpoint re-discovery after a local "
                            "credential change did not complete; refusing to reuse "
                            "the previous identity's endpoint."
                        )
                    continue

                # An upstream attempt was made and failed; apply the retry policy.
                break

            if retry_state.attempt + 1 < self._retry_settings.max_attempts:
                await anyio.sleep(retry_state.delay_seconds)

        raise UpstreamSessionError(
            f"Upstream request {operation_name} failed after "
            f"{self._retry_settings.max_attempts} attempts."
        ) from last_error

    async def _rediscover_factory(self) -> None:
        """Re-run URL discovery for the current identity and install the factory.

        Serialized by ``_identity_refresh_lock`` so concurrent requests never run
        overlapping discoveries. Discovery itself is a network call and runs
        without the connection ``_lock`` held. Because the identity can switch
        again *while* a discovery is in flight, the resolved factory is only
        committed when the generation it was resolved for is still current;
        otherwise the stale result is discarded and discovery re-runs for the
        newest identity.
        """
        assert self._credential_tracker is not None
        assert self._factory_resolver is not None

        async with self._identity_refresh_lock:
            while True:
                target_generation = self._credential_tracker.current_generation()
                if self._factory_generation == target_generation:
                    # Already aligned (possibly by a concurrent refresh that ran
                    # while we waited for the lock).
                    return

                credential_client = self._credential_tracker.get_client()
                try:
                    new_factory = await self._factory_resolver(credential_client)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to re-discover MCP server URL after credential "
                        "change: %s",
                        exc,
                    )
                    return

                if self._credential_tracker.current_generation() != target_generation:
                    # The identity switched again mid-discovery, so the endpoint
                    # we just resolved is already stale. Discard it and re-resolve
                    # for the newest identity instead of installing a stale factory.
                    LOGGER.debug(
                        "Identity advanced during re-discovery; re-resolving for "
                        "the newest identity."
                    )
                    continue

                async with self._lock:
                    self._connection_factory = new_factory
                    self._factory_generation = target_generation
                return

    async def _ensure_connection_locked(self, bearer_token: str) -> UpstreamConnection:
        if self._connection is None:
            await self._apply_safety_policy_if_needed(bearer_token)
            self._connection = await self._connection_factory.connect(bearer_token=bearer_token)
            # Tag the connection with the generation of the factory that built
            # it. If a re-discovery is still pending (it failed earlier), the
            # factory — and therefore this connection — is behind the current
            # identity and will be dropped again on the next request.
            self._connection_generation = self._factory_generation
        return self._connection

    async def _apply_safety_policy_if_needed(self, bearer_token: str) -> None:
        """Apply the safety policy to the bearer token before connecting.

        The policy is re-applied whenever the token changes (e.g. after a
        refresh) or when connecting for the first time.
        """
        if not self._safety_policy and not self._allowed_tools:
            return

        if self._policy_applied_for_token == bearer_token:
            LOGGER.debug("Safety policy already applied for current token, skipping.")
            return

        LOGGER.debug("Setting safety policy before upstream connection...")
        try:
            await apply_safety_policy(
                bearer_token,
                self._safety_policy,
                allowed_tools=self._allowed_tools,
            )
            self._policy_applied_for_token = bearer_token
            LOGGER.debug("Safety policy set successfully.")
        except Exception as exc:
            LOGGER.warning("Failed to apply safety policy: %s", exc)
            raise

    async def _close_locked(self) -> None:
        if self._connection is not None:
            connection = self._connection
            self._connection = None
            await connection.close()

    def _retry_states(self) -> list[RetryState]:
        states: list[RetryState] = []
        delay = self._retry_settings.base_delay_seconds
        for attempt in range(self._retry_settings.max_attempts):
            states.append(
                RetryState(
                    attempt=attempt,
                    delay_seconds=min(delay, self._retry_settings.max_delay_seconds),
                )
            )
            delay *= 2
        return states


def _should_force_refresh(error: Exception | None) -> bool:
    if error is None:
        return False
    message = str(error).lower()
    return "401" in message or "403" in message or "unauthorized" in message
