# 阿里云 OpenAPI MCP Server

## [README of English](README-EN.md)

## 📚 目录

- [概述](#概述)
- [技术规格](#技术规格)
- [访问地址](#访问地址)
- [系统 MCP 服务列表](#系统-mcp-服务列表)
  - [基础设施管理](#基础设施管理)
  - [监控与审计](#监控与审计)
  - [合规与治理](#合规与治理)
- [核心能力](#核心能力)
  - [OpenAPI 定制化调优](#openapi-定制化调优)
  - [Terraform As Tools](#terraform-as-tools)
  - [多账号支持](#多账号支持)
  - [自定义 OAuth](#自定义-oauth)
- [快速开始](#快速开始)
  - [远程模式接入](#远程模式接入)
  - [通过本地静态凭证接入](#通过本地静态凭证接入)
- [最佳实践](#最佳实践)
- [遥测可视化](#遥测可视化)
- [本地 MCP Server](#本地-mcp-server)
- [参考文档](#参考文档)

## 概述

阿里云 OpenAPI MCP Server 是阿里云官方托管的远程 MCP 服务，通过 Model Context Protocol (MCP) 为 AI 应用提供阿里云服务的无缝集成能力。无需本地部署，即可覆盖阿里云数万个 OpenAPI，让开发者能够轻松地将阿里云的各种服务能力集成到 AI 工作流中。

我们推荐使用 **API MCP Server Core** 模式。该模式基于远程 CLI 模式运行，通过个位数的核心 tools 即可编排并触达阿里云全量能力（覆盖数万 OpenAPI），适合快速集成、低维护成本的场景。

## 技术规格

- **核心模式**：API MCP Server Core（远程 CLI 模式）
- **支持协议**：SSE (Server-Sent Events)、Streamable HTTP
- **认证方式**：OAuth 2.0
- **API 数量**：支持阿里云数万个 OpenAPI
- **部署方式**：云端托管，零运维

## 访问地址

| 区域 | 访问地址 | 适用场景 |
|------|---------|----------|
| **中国站** | https://api.aliyun.com/mcp | 中国大陆用户 |
| **国际站** | https://api.alibabacloud.com/mcp | 海外及国际用户 |

## 系统 MCP 服务列表

阿里云官方提供了一系列经过精心调优的系统 MCP 服务，针对特定场景进行了优化：

### 基础设施管理

| 服务名称 | 功能描述 |
|---------|---------|
| **Terraform Provider** | 提供阿里云 Terraform Provider 元数据，支持在线验证和执行 Terraform 命令的 Runtime 能力 |
| **配额中心** | 根据云产品名称、配额描述、地域信息等，查询配额中心支持的产品通用配额信息 |
| **资源搜索** | 支持当前账号下有权限资源的搜索和统计功能 |

### 监控与审计

| 服务名称 | 功能描述 |
|---------|---------|
| **操作审计 AI** | 使用 AI 根据场景灵活调用操作审计的 LookupEvents 接口 |
| **权限诊断** | API 请求因无权限被拒绝时，通过 EncodedDiagnosticMessage 进行权限诊断 |

### 合规与治理

| 服务名称 | 功能描述 |
|---------|---------|
| **治理报告** | 基于 GovernanceReport 的 MCP Server |
| **配置审计合规包** | 查询合规包模板、启用指定合规包、查询风险项概况及风险资源清单 |

## 核心能力

### OpenAPI 定制化调优

- 修改 API 描述，使其更适合 AI 理解
- 精简非必填参数，降低调用复杂度
- 优化参数说明，提高 AI 调用准确率

### Terraform As Tools

- **HCL 代码集成**：将 Terraform HCL 代码作为完整工具引入
- **变量自动解析**：Terraform 变量自动转换为工具参数
- **确定性编排**：实现基础设施的确定性部署和管理

### 多账号支持

- **角色扮演**：自动使用角色扮演能力操作特定账号
- **账号切换**：灵活指定操作账号和扮演角色
- **集中管理**：轻松实现多账号 AI 集成管理

### 自定义 OAuth

- **Callback 白名单**：精确控制回调地址白名单
- **Token 生命周期**：灵活设置 access token 和 refresh token 过期时间
- **长期免登录**：最长可实现 1 年免登录

## 快速开始

### 远程模式接入

1. **访问控制台**
   - 中国站用户访问：https://api.aliyun.com/mcp
   - 国际站用户访问：https://api.alibabacloud.com/mcp

2. **OAuth 认证**
   - 配置 OAuth 应用
   - 获取 Access Token
   - 配置 Token 刷新策略

3. **选择服务**
   - 浏览系统 MCP 服务
   - 选择需要的 OpenAPI
   - 自定义 API 参数

### 通过本地静态凭证接入

现在阿里云 API MCP Server 可以通过本地静态凭证直接登录。你可以在本地配置阿里云 AccessKey 或已有凭证文件，然后通过 Alibaba Cloud MCP Proxy 自动换取访问 OpenAPI MCP Server 所需的令牌，无需在 MCP 客户端中手动维护 OAuth Token。

代理工具的安装、MCP 客户端配置、安全策略和预检查说明请参考：[Alibaba Cloud MCP Proxy 使用说明](README-PROXY.md)。

### 本地 Proxy 双协议联合验证

仓库内的 `scripts/mcp_proxy_e2e.py` 会从当前源码启动 Proxy，并通过 stdio
连接运行时传入的远程 MCP 地址。测试目标和凭证不会写入仓库；请先按
`README-PROXY.md` 配置凭证，再通过环境变量传入目标地址。

验证 MCP `2026-07-28`（`auto` 会真实执行 `server/discover`）：

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode auto \
  --log-file /tmp/mcp-proxy-modern.log \
  --list-repeat-count 3 \
  --parallel-list-count 10 \
  --run-protocol-behavior-smoke \
  --run-all-tools-smoke
```

验证 legacy initialize/session 回归：

```bash
uv run python scripts/mcp_proxy_e2e.py \
  --server-url "$MCP_PRE_URL" \
  --mode legacy \
  --log-file /tmp/mcp-proxy-legacy.log \
  --list-repeat-count 3 \
  --parallel-list-count 10 \
  --run-protocol-behavior-smoke \
  --run-all-tools-smoke
```

`--run-readonly-tool-smoke` 会依次验证 ListProducts、ListApis、
ListProductRegions 和 GetApiDefinition；`--list-repeat-count` 可验证同一连接上的
重复请求，`--parallel-list-count` 可验证同一 stdio 连接上的并发请求。使用
`--mode 2026-07-28` 可以跳过 discover，直接验证 modern 业务首包。

`--run-runscript-smoke` 会执行只读 ECS `DescribeRegions`，保留 RunScript
返回的 `processID`，并持续调用 `AlibabaCloud___GetTask` 直到真实终态。
`--run-all-tools-smoke` 会验证预发完整 15 工具契约：检索、文档和命令生成
工具执行真实只读调用，GetPresignedUrl 仅签发 60 秒上传票据且不上传文件，
RunScript/GetTask 执行只读 `DescribeRegions`，RunIaC 使用空参数验证其在创建
进程前返回 `ValidationFailed`。`--run-protocol-behavior-smoke` 还会验证 ping、
未知工具、缺少必填参数以及 prompts/resources 的协议行为；现代协议应拒绝
已移除的非 tools 方法，legacy 则按上游能力转发。`--print-tool-contracts`
仅输出工具名和 input schema 的字段结构，不输出 description 或响应正文。
Proxy debug 日志只记录上游 method、protocol mode、HTTP status 和 session
header 是否存在，不记录 bearer token、工具参数或临时凭证。

## 最佳实践

- 📘 [OpenAPI MCP Server Core 最佳实践](docs/best-practices.md)：介绍如何结合 `Skill` 与 `safety policy`，基于 MCP Server Core 构建高效、安全、适合生产环境的 Agent 集成方案。

## 遥测可视化

MCP Proxy 内置 `telemetry-view` 子命令，可在本地启动 Web 服务浏览插件遥测 trace 数据，支持 session 列表、span 层级树、Timeline / Graph 双视图、全屏浏览和实时更新。

```bash
uvx alibabacloud.mcp-proxy@latest telemetry-view
```

详细说明见 [Proxy 使用文档 - 遥测可视化](README-PROXY.md#遥测可视化telemetry-view)。

## 本地 MCP Server

除了推荐使用的远程 OpenAPI MCP Server，我们也提供了一些基于本地 stdio 模式、按产品维度独立部署的 MCP Server，适合对数据安全性要求高或需要自定义配置的场景。

👉 [查看本地 MCP Server 完整列表](docs/local-mcp-servers.md)

## 参考文档

- 📖 **官方文档**：[OpenAPI MCP Server 使用指南](https://help.aliyun.com/zh/openapi/user-guide/openapi-mcp-server-guide)
- 🔧 **技术支持**：通过阿里云工单系统或官方论坛获取技术支持
- 💬 **社区交流**：加入阿里云开发者社区参与讨论，钉钉群：136325002292
- 通过AgentScope使用示例<https://github.com/agentscope-ai/agentscope/tree/main/examples/alibabacloud_api_mcp>

---

*本文档持续更新中，欢迎提交 Issue 或 PR 贡献内容*
