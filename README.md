# 阿里云 MCP Server 使用指南

## [README of English](README-EN.md)

## 📚 目录

- [概述](#概述)
- [部署模式](#部署模式)
  - [远程模式](#远程模式)
  - [本地模式](#本地模式)
- [远程模式详解](#远程模式详解)
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
- [本地模式详解](#本地模式详解)
  - [运行机制](#运行机制)
  - [服务列表](#服务列表)
    - [数据库服务](#数据库服务)
    - [数据分析服务](#数据分析服务)
    - [DevOps 服务](#devops-服务)
    - [其他服务](#其他服务)
- [快速开始](#快速开始)
  - [远程模式接入](#远程模式接入)
  - [本地模式部署](#本地模式部署)
- [参考文档](#参考文档)

## 概述

阿里云 MCP Server 是一个强大的云服务集成平台，通过 Model Context Protocol (MCP) 为 AI 应用提供阿里云服务的无缝集成能力。该平台支持数万个阿里云 OpenAPI，让开发者能够轻松地将阿里云的各种服务能力集成到 AI 工作流中。

## 部署模式

### 远程模式

通过阿里云官方托管的 OpenAPI MCP Server，无需本地部署即可使用全量阿里云服务。适合快速集成、低维护成本的场景。

### 本地模式

基于 stdio 进程模式，在本地运行 MCP Server。适合对数据安全性要求高、需要自定义配置的场景。

## 远程模式详解

### 技术规格

- **支持协议**：SSE (Server-Sent Events)、Streamable HTTP
- **认证方式**：OAuth 2.0
- **API 数量**：支持阿里云数万个 OpenAPI
- **部署方式**：云端托管，零运维

### 访问地址

| 区域 | 访问地址 | 适用场景 |
|------|---------|----------|
| **中国站** | https://api.aliyun.com/mcp | 中国大陆用户 |
| **国际站** | https://api.alibabacloud.com/mcp | 海外及国际用户 |

### 系统 MCP 服务列表

阿里云官方提供了一系列经过精心调优的系统 MCP 服务，针对特定场景进行了优化：

#### 基础设施管理

| 服务名称 | 功能描述 |
|---------|---------|
| **Terraform Provider** | 提供阿里云 Terraform Provider 元数据，支持在线验证和执行 Terraform 命令的 Runtime 能力 |
| **配额中心** | 根据云产品名称、配额描述、地域信息等，查询配额中心支持的产品通用配额信息 |
| **资源搜索** | 支持当前账号下有权限资源的搜索和统计功能 |

#### 监控与审计

| 服务名称 | 功能描述 |
|---------|---------|
| **操作审计 AI** | 使用 AI 根据场景灵活调用操作审计的 LookupEvents 接口 |
| **权限诊断** | API 请求因无权限被拒绝时，通过 EncodedDiagnosticMessage 进行权限诊断 |

#### 合规与治理

| 服务名称 | 功能描述 |
|---------|---------|
| **治理报告** | 基于 GovernanceReport 的 MCP Server |
| **配置审计合规包** | 查询合规包模板、启用指定合规包、查询风险项概况及风险资源清单 |

### 核心能力

#### OpenAPI 定制化调优

- 修改 API 描述，使其更适合 AI 理解
- 精简非必填参数，降低调用复杂度
- 优化参数说明，提高 AI 调用准确率

#### Terraform As Tools

- **HCL 代码集成**：将 Terraform HCL 代码作为完整工具引入
- **变量自动解析**：Terraform 变量自动转换为工具参数
- **确定性编排**：实现基础设施的确定性部署和管理

#### 多账号支持

- **角色扮演**：自动使用角色扮演能力操作特定账号
- **账号切换**：灵活指定操作账号和扮演角色
- **集中管理**：轻松实现多账号 AI 集成管理

#### 自定义 OAuth

- **Callback 白名单**：精确控制回调地址白名单
- **Token 生命周期**：灵活设置 access token 和 refresh token 过期时间
- **长期免登录**：最长可实现 1 年免登录

## 本地模式详解

### 运行机制

本地模式基于 stdio 进程通信，MCP Server 作为独立进程在本地运行，通过标准输入输出与 AI 应用进行通信。

### 服务列表

#### 数据库服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **DMS** | [alibabacloud-dms-mcp-server](https://github.com/aliyun/alibabacloud-dms-mcp-server) | 数据管理服务，提供数据库管理能力 |
| **RDS** | [alibabacloud-rds-openapi-mcp-server](https://github.com/aliyun/alibabacloud-rds-openapi-mcp-server) | 关系型数据库服务 OpenAPI 集成 |
| **ADBPG** | [alibabacloud-adbpg-mcp-server](https://github.com/aliyun/alibabacloud-adbpg-mcp-server) | 分析型数据库 PostgreSQL 版 |

#### 数据分析服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **DataWorks** | [alibabacloud-dataworks-mcp-server](https://github.com/aliyun/alibabacloud-dataworks-mcp-server) | 数据工场，提供大数据开发治理能力 |

#### DevOps 服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **云效** | [alibabacloud-devops-mcp-server](https://github.com/aliyun/alibabacloud-devops-mcp-server) | 企业级 DevOps 平台集成 |
| **运维开发** | [alibaba-cloud-ops-mcp-server](https://github.com/aliyun/alibaba-cloud-ops-mcp-server) | 运维开发工具集成 |

#### 其他服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **ESA** | [mcp-server-esa](https://github.com/aliyun/mcp-server-esa) | 边缘安全加速服务 |
| **可观测** | [alibabacloud-observability-mcp-server](https://github.com/aliyun/alibabacloud-observability-mcp-server) | 可观测性服务集成 |

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

### 本地模式部署

1. **克隆仓库**
   ```bash
   git clone https://github.com/aliyun/[具体服务仓库名称]
   cd [仓库目录]
   ```

2. **安装依赖**
   ```bash
   npm install  # 或 yarn install
   ```

3. **配置认证**
   ```bash
   export ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key
   export ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_secret_key
   ```

4. **启动服务**
   ```bash
   npm start  # 或按照具体仓库的启动说明
   ```

## 参考文档

- 📖 **官方文档**：[OpenAPI MCP Server 使用指南](https://help.aliyun.com/zh/openapi/user-guide/openapi-mcp-server-guide)
- 🔧 **技术支持**：通过阿里云工单系统或官方论坛获取技术支持
- 💬 **社区交流**：加入阿里云开发者社区参与讨论，钉钉群：136325002292

---

*本文档持续更新中，欢迎提交 Issue 或 PR 贡献内容*
