# MCP Proxy 2026-07-28 双协议实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**目标：** 在不增加端点、不破坏 legacy 用户的前提下，用同一份 Proxy 代码同时支持下游 legacy MCP 和 MCP `2026-07-28`，并将同一 era 固定透传到预发 CloudSpec。

**总体方案：** 将 Proxy 整体升级到 MCP Python SDK v2。SDK v2 在本地 stdio 连接的第一条请求上识别并锁定 era；Proxy 从 `ServerRequestContext.protocol_version` 得到 era，将其显式传入 `ReconnectingSession`，再用固定的 `Client(mode="legacy")` 或 `Client(mode="2026-07-28")` 连接上游。modern 不探测、不降级、不创建 transport session；legacy 保持 initialize、session、重连、token 刷新和 SSE 恢复行为。

**技术栈：** Python 3.10+、MCP Python SDK 2.x、`mcp-types` 2.x、`httpx2` 2.x、AnyIO、aiohttp、pytest、pytest-asyncio、uv。

**设计依据：** `docs/superpowers/specs/2026-07-31-mcp-20260728-dual-protocol-proxy-design.md`

**实施约束：**

- 每个生产代码改动之前先写测试并观察预期失败；
- 每个任务只解决一个边界，focused tests 通过后立即提交；
- 不给新参数设置静默的 legacy 默认值；
- 不在代码、测试或文档中写入预发 URL、bearer token、AK、SK 或 tmpAK；
- modern 只支持 `server/discover`、`tools/list`、`tools/call` 和 `resultType="complete"`；
- `input_required`、Tasks、Apps、subscriptions 和 modern over SSE 都显式拒绝；
- 不改 `cli.py` 的端点选择方式，不新增 CLI flag，不改 `stdio_server.py` 的单入口；
- 联合 E2E 必须同时覆盖 modern 与 legacy，并保留 `processID`、GetTask 终态和真实 `call_cli` 输出。

---

## Task 1：升级 SDK 依赖并建立协议公共类型

**文件：**

- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 修改：`src/alibabacloud/mcp_proxy/transport/http_client.py`
- 新增：`src/alibabacloud/mcp_proxy/protocol.py`
- 新增：`tests/test_protocol.py`
- 修改：`tests/test_http_client.py`

### 1.1 更新依赖并锁定

- [ ] 将依赖改为：

```toml
"httpx2[socks]>=2.9.1",
"mcp>=2.0.0,<3.0.0",
```

- [ ] 只重算当前 lock，不执行无关的全量升级：

```bash
uv lock
uv sync --locked
```

预期：命令退出码为 0，环境中安装 `mcp==2.x`、`mcp-types==2.x` 和 `httpx2==2.x`。

### 1.2 RED：先写协议映射测试

- [ ] 新建 `tests/test_protocol.py`：

```python
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

from alibabacloud.mcp_proxy.protocol import (
    LEGACY_PROTOCOL_MODE,
    MODERN_PROTOCOL_MODE,
    to_upstream_protocol_mode,
)


def test_all_modern_versions_map_to_modern_mode() -> None:
    assert MODERN_PROTOCOL_VERSIONS
    assert {
        to_upstream_protocol_mode(version) for version in MODERN_PROTOCOL_VERSIONS
    } == {MODERN_PROTOCOL_MODE}


def test_all_handshake_versions_map_to_legacy_mode() -> None:
    assert HANDSHAKE_PROTOCOL_VERSIONS
    assert {
        to_upstream_protocol_mode(version) for version in HANDSHAKE_PROTOCOL_VERSIONS
    } == {LEGACY_PROTOCOL_MODE}


def test_unknown_non_modern_version_maps_to_legacy_mode() -> None:
    assert to_upstream_protocol_mode("2025-11-25") == LEGACY_PROTOCOL_MODE
```

- [ ] 运行并确认因为模块不存在而失败：

```bash
uv run pytest tests/test_protocol.py -q
```

预期：`ModuleNotFoundError: No module named 'alibabacloud.mcp_proxy.protocol'`。

### 1.3 GREEN：实现公共类型和不可重试错误

- [ ] 新建 `src/alibabacloud/mcp_proxy/protocol.py`：

```python
from __future__ import annotations

from typing import Final, Literal

from mcp_types.version import MODERN_PROTOCOL_VERSIONS

ProtocolMode = Literal["2026-07-28", "legacy"]

MODERN_PROTOCOL_MODE: Final[ProtocolMode] = "2026-07-28"
LEGACY_PROTOCOL_MODE: Final[ProtocolMode] = "legacy"


class NonRetryableProxyError(RuntimeError):
    """Base class for permanent protocol and feature errors."""


class ProtocolModeMismatchError(NonRetryableProxyError):
    """Raised when one downstream connection attempts to mix eras."""


class UnsupportedProtocolTransportError(NonRetryableProxyError):
    """Raised when a protocol era cannot use the selected transport."""


class UnsupportedProtocolFeatureError(NonRetryableProxyError):
    """Raised when the upstream requests a feature outside proxy scope."""


def to_upstream_protocol_mode(protocol_version: str) -> ProtocolMode:
    if protocol_version in MODERN_PROTOCOL_VERSIONS:
        return MODERN_PROTOCOL_MODE
    return LEGACY_PROTOCOL_MODE
```

- [ ] 将 `transport/http_client.py` 和 `tests/test_http_client.py` 的直接依赖从 `httpx` 改为 `httpx2`，返回类型改为 `httpx2.AsyncClient`。

- [ ] SOCKS 诊断中的安装建议同步改为：

```text
'httpx2[socks]'
```

- [ ] 运行：

```bash
uv run pytest tests/test_protocol.py tests/test_http_client.py -q
```

预期：两组测试全部通过。

### 1.4 提交

- [ ] 检查并提交：

```bash
git diff --check
git add pyproject.toml uv.lock \
  src/alibabacloud/mcp_proxy/protocol.py \
  src/alibabacloud/mcp_proxy/transport/http_client.py \
  tests/test_protocol.py tests/test_http_client.py
git commit -m "build: upgrade proxy to MCP SDK v2"
```

---

## Task 2：给 ReconnectingSession 增加 era 绑定

**文件：**

- 修改：`src/alibabacloud/mcp_proxy/session/reconnecting_session.py`
- 修改：`tests/test_reconnecting_session.py`

### 2.1 RED：扩展 fake 和调用签名

- [ ] 修改测试 fake，使 factory 记录 token 与 mode：

```python
from alibabacloud.mcp_proxy.protocol import (
    MODERN_PROTOCOL_MODE,
    NonRetryableProxyError,
    ProtocolMode,
    ProtocolModeMismatchError,
)


class FakeConnectionFactory:
    def __init__(self, *, fail_first_connection: bool = True) -> None:
        self.fail_first_connection = fail_first_connection
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
            fail_once=self.fail_first_connection and not self.connections
        )
        self.connections.append(connection)
        return connection
```

- [ ] 所有既有测试调用显式增加 `protocol_mode="legacy"`；不得在生产签名里提供默认值。

- [ ] 增加以下测试：

```python
@pytest.mark.asyncio
async def test_first_request_binds_protocol_mode_and_passes_it_to_factory() -> None:
    token_provider = FakeTokenProvider(["token"])
    factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert factory.connect_calls == [("token", MODERN_PROTOCOL_MODE)]


@pytest.mark.asyncio
async def test_protocol_mode_mismatch_is_rejected_without_token_or_reconnect() -> None:
    token_provider = FakeTokenProvider(["token"])
    factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        factory,
        token_provider,
        RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    await session.list_tools(protocol_mode="legacy")

    with pytest.raises(ProtocolModeMismatchError, match="already bound"):
        await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert token_provider.calls == [False]
    assert factory.connect_calls == [("token", "legacy")]
    assert factory.connections[0].closed is False


@pytest.mark.asyncio
async def test_aclose_clears_protocol_mode_binding() -> None:
    token_provider = FakeTokenProvider(["token"])
    factory = FakeConnectionFactory(fail_first_connection=False)
    session = ReconnectingSession(
        factory,
        token_provider,
        RetrySettings(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    await session.list_tools(protocol_mode="legacy")
    await session.aclose()
    await session.list_tools(protocol_mode=MODERN_PROTOCOL_MODE)

    assert factory.connect_calls == [
        ("token", "legacy"),
        ("token", MODERN_PROTOCOL_MODE),
    ]
```

- [ ] 再增加：

  - `test_reconnect_preserves_bound_protocol_mode`
  - `test_non_retryable_proxy_error_is_not_retried_or_wrapped`
  - `test_tool_error_result_is_returned_without_retry`

- [ ] 运行并确认签名不匹配：

```bash
uv run pytest tests/test_reconnecting_session.py -q
```

预期：测试因 `protocol_mode` 尚未被生产代码接受而失败。

### 2.2 GREEN：显式传递、绑定并保持 era

- [ ] 将 factory protocol 改为：

```python
class UpstreamConnectionFactory(Protocol):
    async def connect(
        self,
        *,
        bearer_token: str,
        protocol_mode: ProtocolMode,
    ) -> UpstreamConnection:
        ...
```

- [ ] 给六个公开 RPC 方法增加 keyword-only `protocol_mode`，例如：

```python
async def list_tools(
    self,
    *,
    protocol_mode: ProtocolMode,
) -> types.ListToolsResult:
    return await self._run_with_retries(
        "tools/list",
        protocol_mode,
        lambda connection: connection.list_tools(),
    )


async def call_tool(
    self,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    protocol_mode: ProtocolMode,
) -> types.CallToolResult:
    return await self._run_with_retries(
        f"tools/call:{name}",
        protocol_mode,
        lambda connection: connection.call_tool(name, arguments),
    )
```

- [ ] 在 `__init__` 中增加：

```python
self._bound_protocol_mode: ProtocolMode | None = None
```

- [ ] 在取 token 之前绑定 era：

```python
def _bind_protocol_mode_locked(self, protocol_mode: ProtocolMode) -> None:
    if self._bound_protocol_mode is None:
        self._bound_protocol_mode = protocol_mode
        return
    if self._bound_protocol_mode != protocol_mode:
        raise ProtocolModeMismatchError(
            "Upstream protocol mode is already bound to "
            f"{self._bound_protocol_mode!r}; cannot switch to {protocol_mode!r}."
        )
```

- [ ] `_run_with_retries` 的顺序必须是：

```python
async with self._lock:
    self._bind_protocol_mode_locked(protocol_mode)
    force_refresh = retry_state.attempt > 0 and _should_force_refresh(last_error)
    token = await self._token_provider.get_token(force_refresh=force_refresh)
    try:
        connection = await self._ensure_connection_locked(token, protocol_mode)
        return await callback(connection)
    except (ProxyDependencyError, NonRetryableProxyError):
        raise
    except Exception as exc:
        last_error = exc
        stale_connection = self._connection
        self._connection = None
```

- [ ] 建连时透传 mode：

```python
self._connection = await self._connection_factory.connect(
    bearer_token=bearer_token,
    protocol_mode=protocol_mode,
)
```

- [ ] 普通失败和重连只清 `_connection`，不清 `_bound_protocol_mode`。只有显式 `aclose()` 在 `finally` 中清绑定：

```python
async def aclose(self) -> None:
    async with self._lock:
        try:
            await self._close_locked()
        finally:
            self._bound_protocol_mode = None
```

- [ ] `_should_force_refresh` 先检查结构化状态，再保留旧字符串兼容：

```python
status_code = getattr(error, "status_code", None)
if status_code in (401, 403):
    return True
message = str(error).lower()
return "401" in message or "403" in message or "unauthorized" in message
```

- [ ] 运行：

```bash
uv run pytest tests/test_reconnecting_session.py -q
```

预期：全部通过，旧 token refresh、安全策略和连接复用断言仍在。

### 2.3 提交

- [ ] 提交：

```bash
git diff --check
git add src/alibabacloud/mcp_proxy/session/reconnecting_session.py \
  tests/test_reconnecting_session.py
git commit -m "feat: bind upstream sessions to protocol era"
```

---

## Task 3：将 Streamable HTTP 上游迁移到 SDK v2

**文件：**

- 修改：`src/alibabacloud/mcp_proxy/transport/upstream_http.py`
- 修改：`tests/test_upstream_http.py`
- 修改：`tests/test_session_marker.py`

### 3.1 RED：modern wire 与 legacy 顺序测试

- [ ] 在 `tests/test_upstream_http.py` 中用真实 aiohttp server 记录每个 POST 的：

```python
received: list[dict[str, object]] = []

received.append(
    {
        "method": payload["method"],
        "headers": dict(request.headers),
        "params": payload.get("params"),
    }
)
```

- [ ] 新增以下测试：

  - `test_modern_list_tools_is_first_request_and_has_modern_envelope`
  - `test_modern_call_tool_has_protocol_method_and_name_headers`
  - `test_modern_connection_does_not_send_discover_initialize_or_initialized`
  - `test_legacy_connection_preserves_initialize_initialized_business_order`
  - `test_legacy_session_id_is_sent_on_following_requests`

- [ ] modern `tools/list` mock 必须返回严格合法的 0728 wire：

```python
return web.json_response(
    {
        "jsonrpc": "2.0",
        "id": payload["id"],
        "result": {
            "tools": [],
            "resultType": "complete",
            "ttlMs": 0,
            "cacheScope": "private",
        },
    }
)
```

- [ ] 对 modern 第一包断言：

```python
assert [entry["method"] for entry in received] == ["tools/list"]
headers = received[0]["headers"]
params = received[0]["params"]
assert headers["MCP-Protocol-Version"] == "2026-07-28"
assert headers["Mcp-Method"] == "tools/list"
assert "Mcp-Session-Id" not in headers
meta = params["_meta"]
assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
assert "io.modelcontextprotocol/clientInfo" in meta
assert "io.modelcontextprotocol/clientCapabilities" in meta
```

- [ ] 对 modern `tools/call` 再断言 `Mcp-Name` 等于工具名；对 legacy 顺序断言：

```python
assert methods == [
    "initialize",
    "notifications/initialized",
    "tools/list",
]
```

- [ ] factory 的所有调用都显式传：

```python
await factory.connect(
    bearer_token="test-token",
    protocol_mode="2026-07-28",
)
```

或：

```python
await factory.connect(
    bearer_token="test-token",
    protocol_mode="legacy",
)
```

- [ ] 运行 RED：

```bash
uv run pytest tests/test_upstream_http.py -q
```

预期：因 factory 还不接受 `protocol_mode`、仍使用旧 `ClientSession` 而失败。

### 3.2 GREEN：使用 Client(mode=...) 管理生命周期

- [ ] 迁移 import：

```python
import httpx2
from mcp import Client, types
```

- [ ] `_RpcRequest` 和 `_dispatch` 的 caller 改为 `Client`：

```python
def __init__(self, caller: Callable[[Client], Awaitable[Any]]) -> None:
    self.caller = caller


async def _dispatch(
    self,
    caller: Callable[[Client], Awaitable[T]],
) -> T:
    request = _RpcRequest(caller)
    await self._request_sender.send(request)
    return await request.wait(self._done_event, self._worker_error_holder)
```

- [ ] worker 签名增加 `protocol_mode: ProtocolMode`，核心生命周期改为：

```python
http_client = create_async_client(
    headers=headers,
    timeout=httpx2.Timeout(
        connect=config.connect_timeout_seconds,
        read=config.read_timeout_seconds,
        write=config.read_timeout_seconds,
        pool=config.connect_timeout_seconds,
    ),
    follow_redirects=True,
    event_hooks=event_hooks,
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
                try:
                    request.set_result(await request.caller(client))
                except BaseException as exc:
                    request.set_error(exc)
```

- [ ] 删除手工 `session.initialize()`，删除旧 `streams[2]` / `get_session_id()`。

- [ ] factory 签名改为：

```python
async def connect(
    self,
    *,
    bearer_token: str,
    protocol_mode: ProtocolMode,
) -> StreamableHttpConnection:
```

- [ ] 保持后台 worker、memory stream、ready/done event 和 cancel-scope 隔离结构不变。

- [ ] 使用底层 session 禁止 SDK 自动驱动 MRTR：

```python
async def call_tool(
    self,
    name: str,
    arguments: dict[str, Any] | None,
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
    return result
```

- [ ] `get_prompt`、`read_resource` 同样调用 `client.session` 并在返回 `InputRequiredResult` 时抛 `UnsupportedProtocolFeatureError`；`list_*` 可使用高层只读方法。

- [ ] 运行：

```bash
uv run pytest tests/test_upstream_http.py -q
```

预期：modern/legacy 顺序与 header 测试通过。

### 3.3 RED：严格 schema、complete、MRTR 和 isError

- [ ] 新增：

  - `test_modern_complete_call_tool_result_is_returned`
  - `test_modern_list_tools_missing_result_type_is_rejected`
  - `test_modern_list_tools_missing_cache_fields_is_rejected`
  - `test_input_required_result_is_rejected_without_replaying_request`
  - `test_is_error_tool_result_is_returned_without_reconnect`

- [ ] `input_required` mock 返回：

```python
{
    "jsonrpc": "2.0",
    "id": payload["id"],
    "result": {
        "resultType": "input_required",
        "requestState": "opaque-state",
    },
}
```

- [ ] 断言：

```python
with pytest.raises(
    UnsupportedProtocolFeatureError,
    match="multi-round requests are not supported",
):
    await connection.call_tool("example", {})

assert methods.count("tools/call") == 1
```

- [ ] 对缺字段用 `pydantic.ValidationError` 或 SDK 暴露的实际 validation error 断言；不得在 Proxy 中给 CloudSpec 的非法 modern 响应补字段。

- [ ] 运行 focused tests，先确认现有实现至少有一条预期失败，再补齐最小代码：

```bash
uv run pytest tests/test_upstream_http.py -q
```

预期：补齐后全部通过；`input_required` 没有第二次 `tools/call`，`isError=True` 原样返回。

### 3.4 RED/GREEN：HTTP 状态保真、脱敏审计和 legacy marker

- [ ] 新增测试：

  - `test_runtime_http_status_is_preserved_for_retry_classification`
  - `test_modern_401_refreshes_token_and_reconnects_without_fallback`
  - `test_legacy_response_hook_writes_session_marker_once`
  - `test_modern_response_never_writes_session_marker`
  - `test_http_audit_logs_only_method_mode_status_and_header_presence`

- [ ] `test_modern_401_refreshes_token_and_reconnects_without_fallback` 必须断言：

```python
assert token_provider.calls == [False, True]
assert methods == ["tools/list", "tools/list"]
assert "initialize" not in methods
assert "server/discover" not in methods
```

- [ ] 审计测试给 tool name、arguments 和 authorization 放入唯一 sentinel，并确认日志完全不含：

```python
assert "secret-token-value" not in caplog.text
assert "secret-tool-argument" not in caplog.text
assert "SensitiveToolName" not in caplog.text
```

- [ ] 先运行并观察 marker/status/audit 测试失败：

```bash
uv run pytest tests/test_upstream_http.py tests/test_session_marker.py -q
```

- [ ] 实现状态对象：

```python
@dataclass(slots=True)
class _HttpAuditState:
    protocol_mode: ProtocolMode
    pending_error_status: int | None = None
    marked_session_id: str | None = None

    def clear_error_status(self) -> None:
        self.pending_error_status = None

    def wrap_error(self, error: BaseException) -> BaseException:
        if self.pending_error_status is None:
            return error
        status_code = self.pending_error_status
        self.pending_error_status = None
        return UpstreamHttpResponseError(status_code, error)
```

- [ ] 实现结构化错误：

```python
class UpstreamHttpResponseError(RuntimeError):
    def __init__(self, status_code: int, cause: BaseException) -> None:
        self.status_code = status_code
        self.__cause__ = cause
        super().__init__(f"Upstream HTTP response status={status_code}")
```

- [ ] request hook 只解析 method，不记录 body：

```python
async def audit_request(request: httpx2.Request) -> None:
    method = request.headers.get("Mcp-Method")
    if method is None and request.method == "POST":
        try:
            method = json.loads(request.content).get("method")
        except (ValueError, TypeError, httpx2.RequestNotRead):
            method = "<unknown>"
    LOGGER.debug(
        "MCP upstream request transport=streamable-http "
        "protocol_mode=%s method=%s session_header_present=%s",
        state.protocol_mode,
        method or "<unknown>",
        "Mcp-Session-Id" in request.headers,
    )
```

- [ ] response hook 只记录状态和 session header 是否存在，并保留 4xx/5xx：

```python
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
```

- [ ] 每个 RPC 前清 error status；RPC 或 startup 抛错时用 `state.wrap_error()` 包装。这样 v2 SDK 转成 `MCPError` 后，401/403 仍能触发既有 token 强制刷新。

- [ ] 运行：

```bash
uv run pytest tests/test_upstream_http.py tests/test_session_marker.py -q
```

预期：全部通过；日志没有 bearer、body、工具名或参数。

### 3.5 提交

- [ ] 提交：

```bash
git diff --check
git add src/alibabacloud/mcp_proxy/transport/upstream_http.py \
  tests/test_upstream_http.py tests/test_session_marker.py
git commit -m "feat: support dual-era upstream HTTP"
```

---

## Task 4：迁移 legacy SSE，modern 明确拒绝

**文件：**

- 修改：`src/alibabacloud/mcp_proxy/transport/upstream_sse.py`
- 修改：`tests/test_upstream_sse.py`
- 修改：`tests/test_reconnecting_session.py`

### 4.1 RED：固定 legacy 回归和 modern 永久错误

- [ ] 将已有测试调用显式改为 `protocol_mode="legacy"`，保留：

  - `test_legacy_session_404_reconnects_and_retries_request`
  - `test_initialize_503_is_retried_with_new_sse_session`

- [ ] 新增：

```python
@pytest.mark.asyncio
async def test_modern_sse_is_rejected_before_network_or_task_group() -> None:
    config = AlibabaCloudProxyConfig.from_mapping(
        {"server_url": "https://does-not-run.example/sse"}
    )
    factory = SseConnectionFactory(config, config.server_url)

    with pytest.raises(
        UnsupportedProtocolTransportError,
        match="2026-07-28.*SSE",
    ):
        await factory.connect(
            bearer_token="unused-token",
            protocol_mode="2026-07-28",
        )
```

- [ ] 在 `tests/test_reconnecting_session.py` 增加 fake factory 抛 `UnsupportedProtocolTransportError` 的断言，确认只有一次 token 获取、一次 factory 调用、无 retry wrapping。

- [ ] 运行 RED：

```bash
uv run pytest tests/test_upstream_sse.py tests/test_reconnecting_session.py -q
```

预期：factory 不接受 mode 或没有永久拒绝逻辑。

### 4.2 GREEN：SSE 使用 v2 Client 且只允许 legacy

- [ ] 迁移 import：

```python
import httpx2
from mcp import Client, types
```

- [ ] 将所有 `httpx` request/response/client 类型改为 `httpx2`。

- [ ] factory 在任何 task-group/network 操作前拒绝 modern：

```python
async def connect(
    self,
    *,
    bearer_token: str,
    protocol_mode: ProtocolMode,
) -> SseConnection:
    if protocol_mode != LEGACY_PROTOCOL_MODE:
        raise UnsupportedProtocolTransportError(
            "MCP 2026-07-28 is not supported over legacy SSE transport."
        )
    if self._task_group is None:
        raise RuntimeError(
            "SseConnectionFactory requires a task group. "
            "Call set_task_group() before connect()."
        )
```

- [ ] worker 使用：

```python
transport = sse_client(
    server_url,
    headers=headers,
    timeout=config.connect_timeout_seconds,
    sse_read_timeout=config.read_timeout_seconds,
    httpx_client_factory=httpx_client_factory,
)

async with Client(
    transport,
    mode=LEGACY_PROTOCOL_MODE,
    cache=None,
) as client:
    ready_event.set()
```

- [ ] 删除手工 `ClientSession.initialize()`，但必须保留 response hook：

  - POST 404 且 body 为 session not found 时取消 worker；
  - POST 5xx 时取消 worker；
  - startup 503 进入 startup error；
  - 运行期 404 进入 worker error，交给 `ReconnectingSession` 重建。

- [ ] `_RpcRequest` caller 改为 `Client`；tool call 使用底层 `client.session.call_tool(..., allow_input_required=True)` 并拒绝 `InputRequiredResult`，避免未来 SSE 路径意外驱动 MRTR。

- [ ] 运行：

```bash
uv run pytest tests/test_upstream_sse.py tests/test_reconnecting_session.py -q
```

预期：旧 404/503 恢复测试通过，modern 只失败一次且没有发网络请求。

### 4.3 提交

- [ ] 提交：

```bash
git diff --check
git add src/alibabacloud/mcp_proxy/transport/upstream_sse.py \
  tests/test_upstream_sse.py tests/test_reconnecting_session.py
git commit -m "refactor: migrate legacy SSE to MCP SDK v2"
```

---

## Task 5：迁移本地 Proxy Server handlers 与 discover

**文件：**

- 修改：`src/alibabacloud/mcp_proxy/proxy/server.py`
- 新增：`tests/test_proxy_server.py`

### 5.1 RED：直接 handler 单测

- [ ] 写一个 recording session，六个方法都记录收到的 `protocol_mode` 和 typed params。

- [ ] 新增：

  - `test_discover_advertises_only_tools_without_accessing_session`
  - `test_list_tools_forwards_modern_protocol_mode`
  - `test_call_tool_forwards_legacy_protocol_mode_and_typed_params`
  - `test_modern_prompts_and_resources_are_rejected_without_upstream_call`
  - `test_handler_preserves_mcp_error`
  - `test_handler_wraps_unexpected_error_as_internal_error`
  - `test_read_resource_returns_text_and_blob_contents_unchanged`

- [ ] discover 断言：

```python
result = await proxy._handle_discover(modern_context, types.RequestParams())

assert result.supported_versions == list(MODERN_PROTOCOL_VERSIONS)
assert result.capabilities.tools is not None
assert result.capabilities.prompts is None
assert result.capabilities.resources is None
assert result.result_type == "complete"
assert recording_session.calls == []
```

- [ ] modern prompt/resource 断言 code 是 `METHOD_NOT_FOUND`，并且 session 没有调用记录。

- [ ] 运行 RED：

```bash
uv run pytest tests/test_proxy_server.py -q
```

预期：旧 handler 签名和旧 `McpError` API 导致测试失败。

### 5.2 GREEN：注册 v2 typed handlers

- [ ] import 改为：

```python
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, METHOD_NOT_FOUND
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
```

- [ ] 通过构造参数注册六类 handler，并覆盖默认 discover：

```python
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
```

- [ ] discover 本地静态返回：

```python
async def _handle_discover(
    self,
    ctx: ServerRequestContext[Any, Any],
    params: types.RequestParams,
) -> types.DiscoverResult:
    return types.DiscoverResult(
        supportedVersions=list(MODERN_PROTOCOL_VERSIONS),
        capabilities=types.ServerCapabilities(
            tools=types.ToolsCapability(),
        ),
    )
```

- [ ] list/call 使用 typed params 和 ctx era：

```python
async def _handle_list_tools(
    self,
    ctx: ServerRequestContext[Any, Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
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
        _LOGGER.error("Upstream tools/call:%s failed: %s", params.name, exc, exc_info=True)
        raise MCPError(code=INTERNAL_ERROR, message=str(exc)) from exc
```

- [ ] legacy-only 方法先 guard：

```python
def _require_legacy(self, ctx: ServerRequestContext[Any, Any]) -> ProtocolMode:
    protocol_mode = to_upstream_protocol_mode(ctx.protocol_version)
    if protocol_mode == MODERN_PROTOCOL_MODE:
        raise MCPError(
            code=METHOD_NOT_FOUND,
            message="Method not found",
        )
    return protocol_mode
```

- [ ] `prompts/list`、`prompts/get`、`resources/list`、`resources/read` 都在任何上游调用前执行 guard。

- [ ] v2 `read_resource` 直接返回上游 `types.ReadResourceResult`；删除旧 `ReadResourceContents`、base64 decode/re-encode 适配，保持 text/blob typed 内容不变。

- [ ] 运行：

```bash
uv run pytest tests/test_proxy_server.py -q
```

预期：全部通过。

### 5.3 提交

- [ ] 提交：

```bash
git diff --check
git add src/alibabacloud/mcp_proxy/proxy/server.py tests/test_proxy_server.py
git commit -m "feat: expose dual-era downstream MCP server"
```

---

## Task 6：增加真实下游双 era 协议流测试

**文件：**

- 新增：`tests/test_downstream_protocol.py`
- 如测试暴露缺口则修改：`src/alibabacloud/mcp_proxy/proxy/server.py`

### 6.1 建立真实 memory transport

- [ ] 测试不能调用 handler 或 SDK DirectDispatcher，必须让 JSON-RPC 通过真实双向 stream：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from mcp import Client
from mcp.server import Server
from mcp.shared.memory import create_client_server_memory_streams


@asynccontextmanager
async def proxy_memory_transport(
    server: Server,
) -> AsyncIterator[tuple[object, object]]:
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
```

- [ ] 如静态类型检查要求具体 stream 类型，使用 `mcp.shared.memory.MessageStream` 替换返回的 `tuple[object, object]`，不改变测试运行行为。

### 6.2 RED/GREEN：modern

- [ ] 新增：

  - `test_modern_auto_mode_discovers_tools_only`
  - `test_modern_tools_list_can_be_first_request_without_discover`
  - `test_modern_tools_call_returns_complete_result`
  - `test_modern_connection_rejects_late_initialize`

- [ ] `mode="auto"` 验证真正发送 discover：

```python
transport = proxy_memory_transport(proxy._server)
async with Client(transport, mode="auto", cache=None) as client:
    assert client.protocol_version == "2026-07-28"
    assert client.server_capabilities.tools is not None
    assert client.server_capabilities.prompts is None
    result = await client.list_tools()
    assert result.result_type == "complete"
```

- [ ] `mode="2026-07-28"` 验证不 discover 也能直接 list/call：

```python
async with Client(
    proxy_memory_transport(proxy._server),
    mode="2026-07-28",
    cache=None,
) as client:
    result = await client.call_tool("ExampleTool", {"value": "ok"})
    assert result.result_type == "complete"
```

- [ ] 首次运行：

```bash
uv run pytest tests/test_downstream_protocol.py -q
```

预期：如 handler/schema/era 绑定有遗漏则失败；只修改真实缺口后重跑至通过。

### 6.3 RED/GREEN：legacy

- [ ] 新增：

  - `test_legacy_client_initialize_and_tools_list`
  - `test_legacy_initialize_advertises_prompts_resources_and_tools`
  - `test_legacy_connection_rejects_modern_envelope`

- [ ] 使用：

```python
async with Client(
    proxy_memory_transport(proxy._server),
    mode="legacy",
    cache=None,
) as client:
    assert client.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS
    assert client.server_capabilities.tools is not None
    assert client.server_capabilities.prompts is not None
    assert client.server_capabilities.resources is not None
    result = await client.list_tools()
    assert result.tools == []
```

- [ ] 用 raw `SessionMessage(JSONRPCRequest(...))` 发送混合 era 请求，断言同一连接被 SDK v2 拒绝，且 recording session 没有跨 era 上游调用。

- [ ] 运行：

```bash
uv run pytest tests/test_downstream_protocol.py tests/test_proxy_server.py -q
```

预期：modern 和 legacy 全部通过，同一连接不能混用 era。

### 6.4 提交

- [ ] 提交：

```bash
git diff --check
git add tests/test_downstream_protocol.py \
  src/alibabacloud/mcp_proxy/proxy/server.py
git commit -m "test: cover downstream dual-era protocol streams"
```

若 `proxy/server.py` 没有新改动，只添加测试文件。

---

## Task 7：增加可复用的 Proxy → CloudSpec 联合 E2E driver

**文件：**

- 新增：`scripts/mcp_proxy_e2e.py`
- 新增：`tests/test_mcp_proxy_e2e.py`
- 修改：`README.md`

### 7.1 RED：纯函数测试

- [ ] 新增以下纯函数测试，不访问网络：

  - `test_extract_process_id_from_structured_content`
  - `test_extract_process_id_from_json_text_content`
  - `test_get_task_status_classifies_all_non_terminal_states`
  - `test_get_task_status_classifies_all_terminal_states`
  - `test_successful_get_task_requires_real_result`
  - `test_driver_command_uses_current_python_and_local_source`
  - `test_sanitize_output_removes_authorization_and_credential_keys`

- [ ] 状态集合固定为：

```python
NON_TERMINAL_STATUSES = {
    "Received",
    "ApprovalPending",
    "Queued",
    "Allocating",
    "Running",
}

TERMINAL_STATUSES = {
    "ValidationFailed",
    "Succeeded",
    "Failed",
    "ApprovalRejected",
    "ApprovalExpired",
    "Expired",
}
```

- [ ] RunScript 调用参数固定为只读命令：

```python
{
    "product": "Ecs",
    "version": "2014-05-26",
    "action": "DescribeRegions",
    "params": {},
}
```

- [ ] 运行 RED：

```bash
uv run pytest tests/test_mcp_proxy_e2e.py -q
```

预期：脚本模块不存在。

### 7.2 GREEN：实现通用 driver

- [ ] driver 接收运行时参数：

```text
--server-url
--mode auto|legacy
--log-file
--poll-interval-seconds
--timeout-seconds
--bearer-token-env
--run-runscript-smoke
```

- [ ] `--server-url` 和凭证均必须来自参数/环境，不设置预发硬编码默认值。

- [ ] 用本地源码启动 Proxy：

```python
server_parameters = StdioServerParameters(
    command=sys.executable,
    args=[
        "-m",
        "alibabacloud.mcp_proxy",
        "--server-url",
        args.server_url,
        "--debug",
        "--log-file",
        args.log_file,
    ],
    env=child_env,
)
```

- [ ] 用官方 v2 Client。`stdio_client(...)` 本身就是 transport context
  manager，直接交给 `Client`，不能先进入它再把裸 streams tuple 传给
  `Client`：

```python
transport = stdio_client(server_parameters)
async with Client(
    transport,
    mode=args.mode,
    cache=None,
) as client:
    if args.mode == "auto":
        assert client.protocol_version == "2026-07-28"
    tools = await client.list_tools()
    print_json({"phase": "tools/list", "result": tools.model_dump(by_alias=True)})
```

- [ ] modern 运行使用 `mode="auto"`，让 driver 真正发送 `server/discover`；legacy 使用 `mode="legacy"`。

- [ ] RunScript/GetTask 主循环：

```python
run_result = await client.call_tool(
    "AlibabaCloud___RunScript",
    {
        "product": "Ecs",
        "version": "2014-05-26",
        "action": "DescribeRegions",
        "params": {},
    },
)
process_id = extract_process_id(run_result)
print_json({"phase": "runscript", "processID": process_id})

deadline = anyio.current_time() + args.timeout_seconds
while True:
    task_result = await client.call_tool(
        "AlibabaCloud___GetTask",
        {"processID": process_id},
    )
    task = extract_task_result(task_result)
    print_json(
        {
            "phase": "get-task",
            "processID": process_id,
            "status": task["status"],
            "waitTimedOut": task.get("waitTimedOut"),
        }
    )
    if task["status"] in TERMINAL_STATUSES:
        break
    if anyio.current_time() >= deadline:
        raise TimeoutError(
            f"GetTask did not reach terminal state for processID={process_id}"
        )
    await anyio.sleep(args.poll_interval_seconds)
```

- [ ] `Succeeded` 验收还必须检查：

```python
if task["status"] != "Succeeded":
    raise RuntimeError(
        f"RunScript failed for processID={process_id}: status={task['status']}"
    )
if task.get("nextAction") is not None:
    raise RuntimeError("Succeeded task unexpectedly requires a next action.")
if task.get("waitTimedOut") is True:
    raise RuntimeError("Succeeded task unexpectedly reports waitTimedOut=true.")
if not task.get("result"):
    raise RuntimeError("Succeeded task did not contain real call_cli output.")
```

- [ ] 输出经过 sanitizer；允许输出 `processID`、状态和 OpenAPI 结果，不输出 authorization、AK/SK、security token、tmpAK 或环境变量值。

- [ ] README 只写通用命令模板：

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode auto \
  --log-file /tmp/mcp-proxy-modern.log \
  --run-runscript-smoke
```

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode legacy \
  --log-file /tmp/mcp-proxy-legacy.log \
  --run-runscript-smoke
```

- [ ] 运行：

```bash
uv run pytest tests/test_mcp_proxy_e2e.py -q
```

预期：纯函数和命令构造测试全部通过。

### 7.3 提交

- [ ] 提交：

```bash
git diff --check
git add scripts/mcp_proxy_e2e.py tests/test_mcp_proxy_e2e.py README.md
git commit -m "test: add MCP proxy preprod E2E driver"
```

---

## Task 8：全量本地验证

**文件：**

- 按失败结果修复任务范围内文件

### 8.1 分层验证

- [ ] 协议与 session：

```bash
uv run pytest \
  tests/test_protocol.py \
  tests/test_reconnecting_session.py \
  tests/test_proxy_server.py \
  tests/test_downstream_protocol.py -q
```

- [ ] transport：

```bash
uv run pytest \
  tests/test_http_client.py \
  tests/test_upstream_http.py \
  tests/test_upstream_sse.py \
  tests/test_session_marker.py -q
```

- [ ] 全量：

```bash
uv run pytest -q
```

预期：原 88 个测试和全部新增测试均通过；不得删除或 xfail 原测试。

### 8.2 构建与静态完整性

- [ ] 运行：

```bash
uv lock --check
uv run python -m compileall -q src tests scripts
uv build
git diff --check
git status --short
```

预期：

- lock 与 `pyproject.toml` 一致；
- compileall 退出码 0；
- sdist 和 wheel 构建成功；
- 无空白错误；
- status 只包含本任务明确产生的预期文件，或已全部提交而为空。

- [ ] 检查旧 SDK/API 残留：

```bash
rg -n \
  "from mcp import ClientSession|from mcp.shared.exceptions import McpError|import httpx$|McpError\\(ErrorData|streams\\[2\\]" \
  src tests
```

预期：无匹配。

### 8.3 兼容性审计

- [ ] 逐条确认：

  - `cli.py` 没有新必填参数；
  - `stdio_server.py` 仍是唯一 stdio 入口；
  - legacy HTTP 仍 initialize 并使用 session；
  - legacy SSE 404/503 回归通过；
  - modern HTTP 第一包是业务请求；
  - modern 没有 discover/initialize/session；
  - modern+SSE 是单次永久错误；
  - bearer token 获取、刷新、安全策略和 allowed tools 逻辑未改变；
  - Proxy 没有新增 tmpAK 逻辑；
  - 日志只包含脱敏协议审计字段。

- [ ] 如本阶段产生修复，单独提交：

```bash
git add src tests scripts pyproject.toml uv.lock README.md
git commit -m "test: complete dual-protocol regression coverage"
```

只有存在实际变更时才执行该提交。

---

## Task 9：本地 Proxy → 预发 CloudSpec 联合 E2E

**文件：**

- 不修改源码；证据保存在临时目录或用户指定位置，不提交凭证或预发地址

### 9.1 环境准备

- [ ] 确认当前运行的是本地分支源码：

```bash
uv run python -c \
  "import alibabacloud.mcp_proxy as p; print(p.__file__)"
```

预期：路径位于当前 worktree 的 `src/alibabacloud/mcp_proxy`。

- [ ] 使用 `/Users/pl/IdeaProjects-new/cloudspec/end-to-end-test-guide.md` 取得当次预发地址和认证方式，只通过 shell 环境传入。

- [ ] 先运行无凭证输出的 precheck；不在命令行回显 bearer token。

### 9.2 modern 联合测试

- [ ] 执行：

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode auto \
  --log-file /tmp/mcp-proxy-modern.log \
  --run-runscript-smoke
```

- [ ] 保存并核对：

  - discover 协商为 `2026-07-28`；
  - discover capabilities 只有 tools；
  - `tools/list.resultType == "complete"`；
  - RunScript 返回 `processID`；
  - GetTask 轮询到 `Succeeded`；
  - `nextAction is None`；
  - `waitTimedOut is False`；
  - result 中存在真实 `DescribeRegions` / `call_cli` 输出。

- [ ] 检查脱敏日志：

```bash
rg -n \
  "MCP upstream (request|response).*protocol_mode=2026-07-28" \
  /tmp/mcp-proxy-modern.log
```

预期：

- 第一条上游 request method 是 `tools/list` 或 E2E driver 首个实际业务方法；
- 没有 `server/discover`；
- 没有 `initialize`；
- 所有 request/response 都是 `session_header_present=False`；
- 日志没有 bearer、tool arguments、AK/SK/tmpAK。

### 9.3 legacy 联合回归

- [ ] 执行：

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode legacy \
  --log-file /tmp/mcp-proxy-legacy.log \
  --run-runscript-smoke
```

- [ ] 保存并核对：

  - legacy initialize 成功；
  - list tools 成功；
  - RunScript/GetTask 同样到真实 `Succeeded`；
  - 保留第二个 `processID` 和实际 `call_cli` 输出。

- [ ] 检查脱敏日志：

```bash
rg -n \
  "MCP upstream (request|response).*protocol_mode=legacy" \
  /tmp/mcp-proxy-legacy.log
```

预期：

- 有 `initialize`；
- initialize 响应出现 `session_header_present=True`；
- 后续业务 request 出现 `session_header_present=True`；
- 没有凭证或请求参数。

### 9.4 失败边界

- [ ] 若 E2E 失败，报告必须分开写：

  - Proxy 本地协议失败；
  - CloudSpec 预发协议/schema 失败；
  - 认证失败；
  - RunScript 排队/审批/执行失败；
  - GetTask 超时；
  - 真实 OpenAPI 调用失败。

- [ ] HTTP metadata 200、Proxy 启动成功、工具返回 `processID` 都不能替代 GetTask 真实终态。

- [ ] 修复任何源码问题时回到对应 Task 的 RED/GREEN 测试，新增回归后再重跑 Task 8 和本任务。

---

## Task 10：最终审查与交付

### 10.1 规格覆盖检查

- [ ] 对照设计文档第 13 节逐条勾选；
- [ ] 确认没有新端点、没有新必填参数、没有上游 probe/fallback；
- [ ] 确认同一 session 混 era 会失败；
- [ ] 确认 Proxy 仍只管理 bearer，CloudSpec 继续独立负责 tmpAK；
- [ ] 确认 modern scope 没有意外扩展到 MRTR、Tasks、Apps 或 subscriptions；
- [ ] 确认 legacy prompts/resources/tools、HTTP、SSE、重连和认证测试仍通过。

### 10.2 代码审查

- [ ] 使用 `superpowers:requesting-code-review` 对完整 diff 做独立审查；
- [ ] 修复 P0/P1/P2 问题并为每个行为问题补测试；
- [ ] 重跑 Task 8 全量验证；
- [ ] 如修复影响 runtime，重跑 Task 9 的 modern 与 legacy E2E。

### 10.3 交付

- [ ] 检查提交：

```bash
git log --oneline --decorate origin/main..HEAD
git status --short --branch
```

- [ ] 最终报告分别给出：

  - 分支和 commit 列表；
  - 单元测试总数；
  - lock、compile、build、diff check 结果；
  - modern E2E 的协商版本、`processID`、GetTask 终态和 `call_cli` 摘要；
  - legacy E2E 的协商版本、`processID`、GetTask 终态和 `call_cli` 摘要；
  - 脱敏 transport 证据；
  - 未完成或外部阻塞项。

- [ ] 只有用户明确要求时才 push：

```bash
git push -u origin codex/mcp-20260728-dual-protocol
```
