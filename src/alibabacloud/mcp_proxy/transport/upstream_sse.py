from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio
from anyio.abc import TaskGroup

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup  # type: ignore[no-redef]
from mcp import ClientSession, types
from mcp.client.sse import sse_client
from pydantic import AnyUrl

from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class _RpcRequest:
    """A single RPC request dispatched to the background SSE task."""

    __slots__ = ("caller", "result_event", "result", "error")

    def __init__(self, caller: Callable[[ClientSession], Awaitable[Any]]) -> None:
        self.caller = caller
        self.result_event = anyio.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def set_result(self, value: Any) -> None:
        self.result = value
        self.result_event.set()

    def set_error(self, exc: BaseException) -> None:
        self.error = exc
        self.result_event.set()

    async def wait(self) -> Any:
        await self.result_event.wait()
        if self.error is not None:
            raise self.error
        return self.result


class SseConnection:
    """A long-lived upstream SSE connection that reuses the same session.

    The ``sse_client`` context manager creates an internal ``TaskGroup`` with
    its own cancel scope.  If that cancel scope leaks into the caller's task,
    any subsequent ``CancelScope.__enter__/__exit__`` in the same task (e.g.
    the proxy server's ``RequestResponder``) will fail with::

        RuntimeError: Attempted to exit a cancel scope that isn't the
        current tasks's current cancel scope

    To isolate the cancel-scope stack, the entire ``sse_client`` lifecycle
    runs inside a **dedicated background task**.  RPC calls are dispatched
    to that task via a memory-object stream and results are returned via
    per-request ``anyio.Event`` objects.
    """

    def __init__(
        self,
        request_sender: anyio.abc.ObjectSendStream[_RpcRequest | None],
        done_event: anyio.Event,
    ) -> None:
        self._request_sender = request_sender
        self._done_event = done_event

    async def _dispatch(
        self,
        caller: Callable[[ClientSession], Awaitable[T]],
    ) -> T:
        request: _RpcRequest = _RpcRequest(caller)
        await self._request_sender.send(request)
        return await request.wait()

    async def list_prompts(self) -> types.ListPromptsResult:
        return await self._dispatch(lambda s: s.list_prompts())

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        return await self._dispatch(lambda s: s.get_prompt(name, arguments))

    async def list_resources(self) -> types.ListResourcesResult:
        return await self._dispatch(lambda s: s.list_resources())

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        return await self._dispatch(lambda s: s.read_resource(uri))

    async def list_tools(self) -> types.ListToolsResult:
        return await self._dispatch(lambda s: s.list_tools())

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        return await self._dispatch(
            lambda s: s.call_tool(name, arguments or {})
        )

    async def close(self) -> None:
        """Signal the background SSE task to shut down and wait for it."""
        try:
            await self._request_sender.send(None)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            pass
        # Wait for the background task to finish its cleanup.
        await self._done_event.wait()


async def _sse_background_worker(
    server_url: str,
    config: AlibabaCloudProxyConfig,
    headers: dict[str, str],
    request_receiver: anyio.abc.ObjectReceiveStream[_RpcRequest | None],
    ready_event: anyio.Event,
    done_event: anyio.Event,
    startup_error_holder: list[BaseException],
) -> None:
    """Background task that owns the sse_client context.

    All cancel scopes created by ``sse_client`` and ``ClientSession`` live
    entirely within this task, so they never interfere with the caller's
    cancel-scope stack.

    **Important**: all exceptions are caught and handled here so they never
    propagate into the host ``TaskGroup`` (which would crash the entire
    proxy with ``"unhandled errors in a TaskGroup"``).
    """
    try:
        async with sse_client(
            server_url,
            headers=headers,
            timeout=config.connect_timeout_seconds,
            sse_read_timeout=config.read_timeout_seconds,
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                # Signal that the session is ready.
                ready_event.set()

                async with request_receiver:
                    async for request in request_receiver:
                        if request is None:
                            # Shutdown signal.
                            break
                        try:
                            result = await request.caller(session)
                            request.set_result(result)
                        except BaseException as exc:
                            request.set_error(exc)
    except BaseException as exc:
        # Flatten ExceptionGroup for clearer logging.
        root_cause = exc
        if isinstance(exc, BaseExceptionGroup):
            exceptions = exc.exceptions
            if len(exceptions) == 1:
                root_cause = exceptions[0]

        if not ready_event.is_set():
            startup_error_holder.append(root_cause)
            ready_event.set()
        else:
            LOGGER.error("SSE background worker crashed: %s", root_cause, exc_info=True)
    finally:
        done_event.set()


class SseConnectionFactory:
    """Factory that creates SSE connections with background worker tasks.

    Requires an external ``TaskGroup`` (passed via ``set_task_group``) to
    spawn background workers.  This ensures the ``sse_client``'s cancel
    scope lives in a dedicated child task, not in the caller's task.
    """

    def __init__(self, config: AlibabaCloudProxyConfig, server_url: str) -> None:
        self._config = config
        self._server_url = server_url
        self._task_group: TaskGroup | None = None

    def set_task_group(self, task_group: TaskGroup) -> None:
        """Attach the long-lived task group used to spawn SSE workers."""
        self._task_group = task_group

    def _build_headers(self, bearer_token: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {bearer_token}",
            "user-agent": "alibabacloud-mcp-proxy/0.1.0",
        }

    async def connect(self, *, bearer_token: str) -> SseConnection:
        """Create a new SSE connection running in a background task.

        The ``sse_client`` context (and its internal ``TaskGroup``) lives
        entirely inside a background task spawned on the external task
        group.  This keeps the caller's cancel-scope stack clean.
        """
        if self._task_group is None:
            raise RuntimeError(
                "SseConnectionFactory requires a task group. "
                "Call set_task_group() before connect()."
            )

        request_sender, request_receiver = (
            anyio.create_memory_object_stream[_RpcRequest | None](16)
        )
        ready_event = anyio.Event()
        done_event = anyio.Event()
        startup_error_holder: list[BaseException] = []
        headers = self._build_headers(bearer_token)

        # Spawn the worker in the external task group so the sse_client's
        # cancel scope is confined to the child task.
        self._task_group.start_soon(
            _sse_background_worker,
            self._server_url,
            self._config,
            headers,
            request_receiver,
            ready_event,
            done_event,
            startup_error_holder,
        )

        # Wait for the SSE session to be ready (or fail).
        await ready_event.wait()

        if startup_error_holder:
            raise startup_error_holder[0]

        return SseConnection(
            request_sender=request_sender,
            done_event=done_event,
        )