# 本地 MCP Server 列表

阿里云提供了一系列基于 stdio 进程模式的本地 MCP Server，按产品维度独立部署，适合对数据安全性要求高、需要自定义配置的场景。

## 运行机制

本地模式基于 stdio 进程通信，MCP Server 作为独立进程在本地运行，通过标准输入输出与 AI 应用进行通信。

## 部署方式

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

## 服务列表

### 数据库服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **DMS** | [alibabacloud-dms-mcp-server](https://github.com/aliyun/alibabacloud-dms-mcp-server) | 数据管理服务，提供数据库管理能力 |
| **RDS** | [alibabacloud-rds-openapi-mcp-server](https://github.com/aliyun/alibabacloud-rds-openapi-mcp-server) | 关系型数据库服务 OpenAPI 集成 |
| **ADBPG** | [alibabacloud-adbpg-mcp-server](https://github.com/aliyun/alibabacloud-adbpg-mcp-server) | 分析型数据库 PostgreSQL 版 |

### 数据分析服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **DataWorks** | [alibabacloud-dataworks-mcp-server](https://github.com/aliyun/alibabacloud-dataworks-mcp-server) | 数据工场，提供大数据开发治理能力 |

### DevOps 服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **云效** | [alibabacloud-devops-mcp-server](https://github.com/aliyun/alibabacloud-devops-mcp-server) | 企业级 DevOps 平台集成 |
| **运维开发** | [alibaba-cloud-ops-mcp-server](https://github.com/aliyun/alibaba-cloud-ops-mcp-server) | 运维开发工具集成 |

### 其他服务

| 服务 | 仓库地址 | 描述 |
|------|---------|------|
| **ESA** | [mcp-server-esa](https://github.com/aliyun/mcp-server-esa) | 边缘安全加速服务 |
| **可观测** | [alibabacloud-observability-mcp-server](https://github.com/aliyun/alibabacloud-observability-mcp-server) | 可观测性服务集成 |
