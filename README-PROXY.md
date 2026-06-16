# Alibaba Cloud MCP Proxy 使用说明

Alibaba Cloud MCP Proxy 是一个本地 stdio MCP 代理，用于连接阿里云 OpenAPI MCP Server。它负责在本地处理认证、连接管理、重试和安全策略，让 Claude Desktop、Cursor 等 MCP 客户端可以通过本地静态凭证直接接入阿里云 API MCP Server。

## 前置权限

运行代理的 RAM 用户或角色需要具备以下权限：

阿里云已支持系统权限策略 `AliyunOpenAPIMCPServerStaticCredentialAccess`（Access 全量权限，表示通过静态凭证连接权限）。

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ram:GenerateAccessToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "openapiexplorer:*",
      "Resource": "*"
    }
  ]
}
```

- `ram:GenerateAccessToken`：用于通过 IMS 获取 Bearer Token。
- `openapiexplorer:*`：用于发现 MCP Server 和调用工具。

## 快速开始

通过 `uvx` 直接运行最新版代理：

```bash
uvx alibabacloud.mcp-proxy@latest
```

如果需要指定自定义 MCP Server 地址：

```bash
uvx alibabacloud.mcp-proxy@latest --server-url <YOUR_MCP_SERVER_URL>
```

## MCP 客户端配置

在 Claude Desktop、Cursor 等 MCP 客户端配置中添加：

```json
{
  "mcpServers": {
    "alibabacloud": {
      "command": "uvx",
      "args": ["alibabacloud.mcp-proxy@latest"]
    }
  }
}
```

代理会读取本地阿里云静态凭证，并自动换取连接远端 OpenAPI MCP Server 所需的访问令牌。

## 本地静态凭证登录

现在阿里云 API MCP Server 可以通过本地静态凭证直接登录。你可以使用阿里云 CLI 或环境变量配置本地凭证，MCP Proxy 会在本地读取凭证并调用 IMS `GenerateAccessToken` 获取 Bearer Token，无需在 MCP 客户端中手动维护 OAuth Token。

常见环境变量配置方式：

```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key_id
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_access_key_secret
uvx alibabacloud.mcp-proxy@latest
```

## 安全策略

可以通过 `--safety-policy` 限制允许调用的 MCP 工具。安全策略会在连接上游 MCP Server 前应用到访问令牌上。

例如只允许 ECS 查询类操作：

```bash
uvx alibabacloud.mcp-proxy@latest --safety-policy "ecs:describe-*=allow,*=deny"
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "alibabacloud": {
      "command": "uvx",
      "args": [
        "alibabacloud.mcp-proxy@latest",
        "--safety-policy", "ecs:describe-*=allow,*=deny"
      ]
    }
  }
}
```

也可以使用环境变量：

```bash
export ALIBABACLOUD_MCP_SAFETY_POLICY="ecs:describe-*=allow,*=deny"
uvx alibabacloud.mcp-proxy@latest
```

## 预检查（可选）

当使用默认的 Client ID 时，无需单独执行预检查，代理会自动完成认证流程。

如果指定了自定义的 `--client-id`，可以使用 `pre-check` 检查该 OAuth 应用是否正确安装和授权：

```bash
uvx alibabacloud.mcp-proxy@latest pre-check --client-id YOUR_OAUTH_CLIENT_ID
```

国际站：

```bash
uvx alibabacloud.mcp-proxy@latest pre-check --client-id YOUR_OAUTH_CLIENT_ID --site-type INTL
```

## 插件遥测上报（Plugin Telemetry）

为了帮助持续改进 MCP Proxy 的稳定性与体验，本工具提供 `plugin-telemetry` 子命令，**由调用方按需主动上报**一次操作的执行轨迹（trace）。该子命令是**可选的、显式触发**的 —— 不调用即不会有任何遥测数据上传，本工具不存在被动收集模式。

### 使用方式

```bash
uvx alibabacloud.mcp-proxy@latest plugin-telemetry \
  --client-name "claude-code" \
  --event-type "mcp_tool_use" \
  --start-timestamp "2026-05-18T10:30:00Z" \
  --tool-name "AlibabaCloud___CallCLI" \
  --session-id "<匿名会话ID>" \
  --status "success" \
  --span-id "span-abc123" \
  --parent-span-id "span-root-000"
```

#### 字段说明与脱敏建议

| 字段 | 必填 | 用途 | 是否可直接上报 |
|------|:----:|------|---------------|
| `--client-name` | ✅ | 调用方标识（如 `claude-code`） | ✅ 可上报 |
| `--event-type` | ✅ | 事件类型（如 `tool_call`、`skill_invocation`） | ✅ 可上报 |
| `--start-timestamp` | ✅ | 开始时间（ISO-8601） | ✅ 可上报 |
| `--end-timestamp` |   | 结束时间 | ✅ 可上报 |
| `--tool-name` | ✅ | 工具名 | ✅ 可上报 |
| `--session-id` | ✅ | 会话 ID | ⚠️ **必须匿名化**，建议使用调用方生成的 UUID |
| `--status` | ✅ | 结果状态（`success` / `failure`） | ✅ 可上报 |
| `--turn` |   | 轮次序号 | ✅ 可上报 |
| `--mcp-tool` |   | MCP 工具标识 | ✅ 可上报 |
| `--skill-name` |   | 技能名 | ✅ 可上报 |
| `--plugin-name` |   | 插件名 | ✅ 可上报 |
| `--tool-request-id` |   | 调用方生成的请求 ID（建议 UUID） | ✅ 可上报 |
| `--span-id` |   | 当前 span 的唯一标识（用于链路追踪） | ✅ 可上报 |
| `--parent-span-id` |   | 父 span 标识（用于构建调用树） | ✅ 可上报 |
| `--cli-command` |   | CLI 命令 | ⚠️ **务必脱敏**：仅保留命令形态，移除参数中的 ID / 凭证 / 文件路径 |
| `--event-tag` |   | 查询摘要 | ⚠️ **务必脱敏**：只放意图分类，不要把用户原始 prompt 直接复制进来 |
| `--error-message` |   | 错误信息 | ⚠️ **务必脱敏**：只保留错误类型与错误码，剔除 token、AK、IP、内网域名等 |

### 隐私说明（Customer Notice）

- **数据用途**：上报数据仅用于阿里云分析 MCP Proxy 的使用模式、错误率与性能瓶颈，不会与任何账号下的具体业务资源关联，也不会用于商业用途。
- **设计原则：必要的 action 与成功状态，不上报敏感信息。** 请勿将以下内容放入 `--cli-command`、`--event-tag`、`--error-message` 等自由文本字段：
  - 阿里云 AccessKey、SecurityToken、Bearer Token、OAuth Code
  - 用户或 RAM 子账号的真实姓名、手机号、邮箱、身份证号
  - 数据库密码、私钥、证书、私有 endpoint
  - 个人身份信息（PII）、内网 IP / 域名
  - 涉及合规（GDPR / PIPL 等）的客户业务数据
- **建议在调用前进行本地脱敏**：如不确定字段是否安全，建议在传入 CLI 之前用正则替换掉 `(?i)ak[a-z0-9]{16,}`、`/Users/[^/]+/`、邮箱、手机号、UUID 之类的高风险片段。
- **可选 / 显式触发**：不调用 `plugin-telemetry` 即不会有任何上报；本工具不会在 `proxy` / `pre-check` 等其它子命令中静默上传。

### 故障行为

`plugin-telemetry` 走"尽力而为（best-effort）"模型：内置最多 4 次尝试、每次连接/读取超时 3 秒，失败时仅在 stderr 输出 WARN/ERROR 日志，**不会**抛出异常或影响调用方主流程。退出码：`0` 成功 / `1` 重试用尽仍失败 / `2` 参数错误。

## 本地遥测可视化（Telemetry View）

`telemetry-view` 子命令会启动一个本地 Web 服务，用于浏览和分析插件遥测产生的 trace 数据。支持多客户端（Claude Code、VS Code、Copilot CLI、Codex、Qoderwork）的 session 浏览、span 层级树、Gantt 时间线、Graph 流程图以及实时更新。

### 启动

```bash
uvx alibabacloud.mcp-proxy@latest telemetry-view
```

默认在 `http://localhost:18321` 启动并自动打开浏览器。

### 选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | `18321` | 本地服务端口 |
| `--no-open` | - | 不自动打开浏览器 |

### 数据来源

自动扫描以下目录中的 JSONL trace 文件：

1. `$ALIBABACLOUD_TELEMETRY_STATE_DIR`（如已设置）
2. `~/.cache/alibabacloud-agent-toolkit/telemetry/`
3. `/tmp/alibabacloud-agent-toolkit-telemetry-<uid>/`

### 功能

- **首页**：展示所有 session 列表，按客户端筛选、关键字搜索、时间范围过滤；顶部统计栏显示总 session 数、各客户端分布和成功率
- **Trace 详情页**：
  - 左侧可折叠的 span 树，右侧可切换 Timeline（Gantt 条形图）和 Graph（按 Turn 分组的流程图）视图
  - Graph 支持鼠标滚轮缩放、拖拽平移、全屏查看，全屏下点击节点显示浮动详情弹窗
  - 点击任意 span 显示完整详细信息（事件类型、工具名、耗时、状态、输入/输出等）
- **实时更新**：通过 SSE 推送新 span，无需手动刷新
- **暗色/亮色主题切换**

## 配置参考

每个 CLI 参数都有对应的环境变量。CLI 参数优先级高于环境变量。

### 连接配置

| CLI 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--server-url` | `ALIBABACLOUD_MCP_SERVER_URL` | 自动发现 | 上游 Alibaba Cloud MCP Streamable HTTP URL。未设置时会通过 `ListApiMcpServerCores` OpenAPI 自动发现。 |
| `--site-type` | `ALIBABACLOUD_MCP_SITE_TYPE` | `CN` | 站点类型：`CN` 中国站，`INTL` 国际站。 |
| `--connect-timeout` | `ALIBABACLOUD_MCP_CONNECT_TIMEOUT` | `10.0` | HTTP 连接超时时间，单位秒。 |
| `--read-timeout` | `ALIBABACLOUD_MCP_READ_TIMEOUT` | `120.0` | HTTP 读取超时时间，单位秒。 |

### 认证配置

| CLI 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--bearer-token` | `ALIBABACLOUD_MCP_BEARER_TOKEN` | - | 显式指定上游 MCP Server 的 Bearer Token。 |
| `--token-command` | `ALIBABACLOUD_MCP_TOKEN_COMMAND` | - | 输出 Bearer Token 或包含 `access_token` 的 JSON 的命令。 |
| `--client-id` | `ALIBABACLOUD_MCP_CLIENT_ID` | 按站点选择 | IMS `GenerateAccessToken` ClientId。 |
| `--scope` | `ALIBABACLOUD_MCP_SCOPE` | `/internal/acs/openapi` | IMS `GenerateAccessToken` Scope。 |
| `--ims-endpoint` | `ALIBABACLOUD_MCP_IMS_ENDPOINT` | 按站点选择 | IMS API Endpoint。 |

### 调试和日志

| CLI 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--debug` | `ALIBABACLOUD_MCP_DEBUG` | `false` | 启用 debug 日志，必须同时设置 `--log-file`。 |
| `--log-file` | `ALIBABACLOUD_MCP_LOG_FILE` | - | 日志文件路径。 |

## 运行要求

- Python >= 3.13

## License

Apache-2.0
