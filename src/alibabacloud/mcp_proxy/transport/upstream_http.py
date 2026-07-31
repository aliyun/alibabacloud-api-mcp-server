from __future__ import annotations

import json
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import anyio
import httpx2
from anyio.abc import TaskGroup

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup  # type: ignore[no-redef]
from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from pydantic import AnyUrl

from alibabacloud.mcp_proxy import __version__
from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig
from alibabacloud.mcp_proxy.protocol import (
    LEGACY_PROTOCOL_MODE,
    ProtocolMode,
    UnsupportedProtocolFeatureError,
)
from alibabacloud.mcp_proxy.session_marker import write_mcp_session_marker
from alibabacloud.mcp_proxy.transport.http_client import create_async_client

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class UpstreamHttpResponseError(RuntimeError):
    """Preserves an upstream HTTP status hidden by the MCP transport."""

    def __init__(self, status_code: int, cause: BaseException) -> None:
        self.status_code = status_code
        self.__cause__ = cause
        super().__init__(f"Upstream HTTP response status={status_code}")


@dataclass(slots=True)
class _HttpAuditState:
    protocol_mode: ProtocolMode
    pending_error_status: int | None = None
    marked_session_id: str | None = None

    def clear(self) -> None:
        self.pending_error_status = None

    def wrap_error(self, error: BaseException) -> BaseException:
        if self.pending_error_status is None:
            return error
        status_code = self.pending_error_status
        self.pending_error_status = None
        if (
            400 <= status_code < 500
            and status_code not in (401, 403)
            and isinstance(error, MCPError)
        ):
            return error
        return UpstreamHttpResponseError(status_code, error)


def _build_http_event_hooks(
    state: _HttpAuditState,
) -> dict[str, list[Callable[..., Awaitable[None]]]]:
    async def audit_request(request: httpx2.Request) -> None:
        method = request.headers.get("Mcp-Method")
        if method is None and request.method == "POST":
            try:
                payload = json.loads(request.content)
                method = payload.get("method") if isinstance(payload, dict) else None
            except (ValueError, TypeError, httpx2.RequestNotRead):
                method = None
        LOGGER.debug(
            "MCP upstream request transport=streamable-http "
            "protocol_mode=%s method=%s session_header_present=%s",
            state.protocol_mode,
            method or "<unknown>",
            "Mcp-Session-Id" in request.headers,
        )

    async def audit_response(response: httpx2.Response) -> None:
        session_id = response.headers.get("Mcp-Session-Id")
        LOGGER.debug(
            "MCP upstream response transport=streamable-http "
            "protocol_mode=%s status=%s session_header_present=%s",
            state.protocol_mode,
            response.status_code,
            session_id is not None,
        )
        if response.request.method == "POST" and response.status_code >= 400:
            state.pending_error_status = response.status_code
        if (
            state.protocol_mode == LEGACY_PROTOCOL_MODE
            and session_id
            and session_id != state.marked_session_id
        ):
            state.marked_session_id = session_id
            write_mcp_session_marker(session_id)

    return {
        "request": [audit_request],
        "response": [audit_response],
    }


class _RpcRequest:
    """A single RPC request dispatched to the background Streamable HTTP task."""

    __slots__ = ("caller", "result_event", "result", "error")

    def __init__(self, caller: Callable[[Client], Awaitable[Any]]) -> None:
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

    async def wait(
        self,
        worker_done_event: anyio.Event,
        worker_error_holder: list[BaseException],
    ) -> Any:
        wake_event = anyio.Event()

        async def wake_when_set(event: anyio.Event) -> None:
            await event.wait()
            wake_event.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(wake_when_set, self.result_event)
            task_group.start_soon(wake_when_set, worker_done_event)
            await wake_event.wait()
            task_group.cancel_scope.cancel()

        if self.error is not None:
            if isinstance(self.error, anyio.get_cancelled_exc_class()):
                await worker_done_event.wait()
                if worker_error_holder:
                    raise worker_error_holder[-1]
            raise self.error
        if not self.result_event.is_set():
            if worker_error_holder:
                raise worker_error_holder[-1]
            raise RuntimeError("Streamable HTTP background worker stopped unexpectedly.")
        return self.result


class StreamableHttpConnection:
    """A long-lived upstream Streamable HTTP connection that reuses the same session.

    The ``streamable_http_client`` context manager creates an internal
    ``TaskGroup`` with its own cancel scope (for the GET SSE stream).
    To isolate the cancel-scope stack, the entire lifecycle runs inside
    a **dedicated background task**.  RPC calls are dispatched to that
    task via a memory-object stream and results are returned via
    per-request ``anyio.Event`` objects.

    This avoids the previous design of creating a fresh session per RPC
    call (connect → initialize → call → close), which was extremely
    wasteful.
    """

    def __init__(
        self,
        request_sender: anyio.abc.ObjectSendStream[_RpcRequest | None],
        done_event: anyio.Event,
        worker_error_holder: list[BaseException],
    ) -> None:
        self._request_sender = request_sender
        self._done_event = done_event
        self._worker_error_holder = worker_error_holder

    async def _dispatch(
        self,
        caller: Callable[[Client], Awaitable[T]],
    ) -> T:
        request: _RpcRequest = _RpcRequest(caller)
        try:
            await self._request_sender.send(request)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            await self._done_event.wait()
            if self._worker_error_holder:
                raise self._worker_error_holder[-1]
            raise
        return await request.wait(self._done_event, self._worker_error_holder)

    async def list_prompts(self) -> types.ListPromptsResult:
        return await self._dispatch(lambda client: client.list_prompts())

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        result = await self._dispatch(
            lambda client: client.session.get_prompt(
                name,
                arguments,
                allow_input_required=True,
            )
        )
        if isinstance(result, types.InputRequiredResult):
            raise UnsupportedProtocolFeatureError(
                "Upstream returned resultType='input_required'; "
                "multi-round requests are not supported by this proxy."
            )
        return result

    async def list_resources(self) -> types.ListResourcesResult:
        return await self._dispatch(lambda client: client.list_resources())

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        result = await self._dispatch(
            lambda client: client.session.read_resource(
                str(uri),
                allow_input_required=True,
            )
        )
        if isinstance(result, types.InputRequiredResult):
            raise UnsupportedProtocolFeatureError(
                "Upstream returned resultType='input_required'; "
                "multi-round requests are not supported by this proxy."
            )
        return result

    async def list_tools(self) -> types.ListToolsResult:
        return await self._dispatch(lambda client: client.list_tools())

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        result = await self._dispatch(
            lambda client: client.session.call_tool(
                name,
                arguments or {},
                allow_input_required=True,
            )
        )
        if isinstance(result, types.InputRequiredResult):
            raise UnsupportedProtocolFeatureError(
                "Upstream returned resultType='input_required'; "
                "multi-round requests are not supported by this proxy."
            )
        if not isinstance(result, types.CallToolResult):
            raise UnsupportedProtocolFeatureError(
                f"Unsupported upstream tools/call result: {type(result).__name__}."
            )
        return result

    async def close(self) -> None:
        """Signal the background task to shut down and wait for it."""
        try:
            await self._request_sender.send(None)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            pass
        await self._done_event.wait()


async def _streamable_http_background_worker(
    server_url: str,
    config: AlibabaCloudProxyConfig,
    headers: dict[str, str],
    protocol_mode: ProtocolMode,
    request_receiver: anyio.abc.ObjectReceiveStream[_RpcRequest | None],
    ready_event: anyio.Event,
    done_event: anyio.Event,
    startup_error_holder: list[BaseException],
    worker_error_holder: list[BaseException],
) -> None:
    """Background task that owns the streamable_http_client context.

    All cancel scopes created by ``streamable_http_client`` and
    ``Client`` live entirely within this task, so they never
    interfere with the caller's cancel-scope stack.

    The session is initialized once and then reused for all subsequent
    RPC calls until the connection is closed or an error occurs.
    """
    audit_state = _HttpAuditState(protocol_mode=protocol_mode)

    try:
        http_client = create_async_client(
            headers=headers,
            timeout=httpx2.Timeout(
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.read_timeout_seconds,
                pool=config.connect_timeout_seconds,
            ),
            follow_redirects=True,
            event_hooks=_build_http_event_hooks(audit_state),
        )
        transport = streamable_http_client(
            server_url,
            http_client=http_client,
            terminate_on_close=False,
        )
        async with http_client:
            async with Client(
                transport,
                mode=protocol_mode,
                cache=None,
            ) as client:
                ready_event.set()

                async with request_receiver:
                    async for request in request_receiver:
                        if request is None:
                            break
                        audit_state.clear()
                        try:
                            result = await request.caller(client)
                            request.set_result(result)
                        except BaseException as exc:
                            request.set_error(audit_state.wrap_error(exc))
    except BaseException as exc:
        root_cause = exc
        if isinstance(exc, BaseExceptionGroup):
            exceptions = exc.exceptions
            if len(exceptions) == 1:
                root_cause = exceptions[0]

        root_cause = audit_state.wrap_error(root_cause)

        if not ready_event.is_set():
            startup_error_holder.append(root_cause)
            ready_event.set()
        else:
            worker_error_holder.append(root_cause)
            LOGGER.error(
                "Streamable HTTP background worker crashed: %s",
                root_cause,
                exc_info=True,
            )
    finally:
        done_event.set()


class StreamableHttpConnectionFactory:
    """Factory that creates Streamable HTTP connections with background worker tasks.

    Requires an external ``TaskGroup`` (passed via ``set_task_group``) to
    spawn background workers, keeping the ``streamable_http_client``'s
    cancel scope in a dedicated child task.
    """

    def __init__(self, config: AlibabaCloudProxyConfig, server_url: str) -> None:
        self._config = config
        self._server_url = server_url
        self._task_group: TaskGroup | None = None

    def set_task_group(self, task_group: TaskGroup) -> None:
        """Attach the long-lived task group used to spawn HTTP workers."""
        self._task_group = task_group

    def _build_headers(self, bearer_token: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {bearer_token}",
            "user-agent": f"alibabacloud-mcp-proxy/{__version__}",
        }

    async def connect(
        self,
        *,
        bearer_token: str,
        protocol_mode: ProtocolMode,
    ) -> StreamableHttpConnection:
        """Create a new Streamable HTTP connection running in a background task."""
        if self._task_group is None:
            raise RuntimeError(
                "StreamableHttpConnectionFactory requires a task group. "
                "Call set_task_group() before connect()."
            )

        request_sender, request_receiver = (
            anyio.create_memory_object_stream[_RpcRequest | None](16)
        )
        ready_event = anyio.Event()
        done_event = anyio.Event()
        startup_error_holder: list[BaseException] = []
        worker_error_holder: list[BaseException] = []
        headers = self._build_headers(bearer_token)

        self._task_group.start_soon(
            _streamable_http_background_worker,
            self._server_url,
            self._config,
            headers,
            protocol_mode,
            request_receiver,
            ready_event,
            done_event,
            startup_error_holder,
            worker_error_holder,
        )

        await ready_event.wait()

        if startup_error_holder:
            raise startup_error_holder[0]

        return StreamableHttpConnection(
            request_sender=request_sender,
            done_event=done_event,
            worker_error_holder=worker_error_holder,
        )
