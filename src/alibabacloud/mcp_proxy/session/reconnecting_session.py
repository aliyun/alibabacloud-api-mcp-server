from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Protocol, TypeVar

import anyio
from mcp import types
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.auth.token_provider import CachedBearerTokenProvider
from alibabacloud.mcp_proxy.config import RetrySettings
from alibabacloud.mcp_proxy.safety_policy import apply_safety_policy

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
    ) -> None:
        self._connection_factory = connection_factory
        self._token_provider = token_provider
        self._retry_settings = retry_settings
        self._safety_policy = safety_policy
        self._allowed_tools = tuple(allowed_tools or ())
        self._connection: UpstreamConnection | None = None
        self._policy_applied_for_token: str | None = None
        self._lock = anyio.Lock()

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
            stale_connection: UpstreamConnection | None = None

            async with self._lock:
                force_refresh = retry_state.attempt > 0 and _should_force_refresh(last_error)
                token = await self._token_provider.get_token(force_refresh=force_refresh)
                connection = await self._ensure_connection_locked(token)

                try:
                    return await callback(connection)
                except Exception as exc:  # pragma: no cover - depends on upstream SDK exceptions
                    last_error = exc
                    LOGGER.warning(
                        "Upstream %s failed on attempt %s/%s: %s",
                        operation_name,
                        retry_state.attempt + 1,
                        self._retry_settings.max_attempts,
                        exc,
                    )
                    # Detach the connection but do NOT close it inside the
                    # lock / exception handler.  Closing SSE connections here
                    # would trigger cancel-scope nesting violations because
                    # sse_client's internal TaskGroup must be exited from a
                    # clean cancel-scope stack.
                    stale_connection = self._connection
                    self._connection = None

            # Close the stale connection *outside* the lock and outside the
            # try/except block so the cancel-scope stack is clean.
            if stale_connection is not None:
                try:
                    await stale_connection.close()
                except Exception:
                    LOGGER.debug("Error closing stale connection (ignored)", exc_info=True)

            if retry_state.attempt + 1 < self._retry_settings.max_attempts:
                await anyio.sleep(retry_state.delay_seconds)

        raise UpstreamSessionError(
            f"Upstream request {operation_name} failed after "
            f"{self._retry_settings.max_attempts} attempts."
        ) from last_error

    async def _ensure_connection_locked(self, bearer_token: str) -> UpstreamConnection:
        if self._connection is None:
            await self._apply_safety_policy_if_needed(bearer_token)
            self._connection = await self._connection_factory.connect(bearer_token=bearer_token)
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
