# Local MCP Server List

Alibaba Cloud provides a series of local MCP Servers based on stdio process mode, independently deployed by product, suitable for scenarios with high data security requirements and the need for custom configuration.

## Operating Mechanism

Local mode is based on stdio process communication, with MCP Server running as an independent process locally, communicating with AI applications through standard input/output.

## Deployment

1. **Clone Repository**
   ```bash
   git clone https://github.com/aliyun/[specific-service-repository-name]
   cd [repository-directory]
   ```

2. **Install Dependencies**
   ```bash
   npm install  # or yarn install
   ```

3. **Configure Authentication**
   ```bash
   export ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key
   export ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_secret_key
   ```

4. **Start Service**
   ```bash
   npm start  # or follow the specific repository's startup instructions
   ```

## Service List

### Database Services

| Service | Repository URL | Description |
|---------|---------------|-------------|
| **DMS** | [alibabacloud-dms-mcp-server](https://github.com/aliyun/alibabacloud-dms-mcp-server) | Data Management Service, provides database management capabilities |
| **RDS** | [alibabacloud-rds-openapi-mcp-server](https://github.com/aliyun/alibabacloud-rds-openapi-mcp-server) | Relational Database Service OpenAPI integration |
| **ADBPG** | [alibabacloud-adbpg-mcp-server](https://github.com/aliyun/alibabacloud-adbpg-mcp-server) | AnalyticDB for PostgreSQL |

### Data Analytics Services

| Service | Repository URL | Description |
|---------|---------------|-------------|
| **DataWorks** | [alibabacloud-dataworks-mcp-server](https://github.com/aliyun/alibabacloud-dataworks-mcp-server) | Data Factory, provides big data development and governance capabilities |

### DevOps Services

| Service | Repository URL | Description |
|---------|---------------|-------------|
| **Apsara DevOps** | [alibabacloud-devops-mcp-server](https://github.com/aliyun/alibabacloud-devops-mcp-server) | Enterprise-level DevOps platform integration |
| **Operations Development** | [alibaba-cloud-ops-mcp-server](https://github.com/aliyun/alibaba-cloud-ops-mcp-server) | Operations development tools integration |

### Other Services

| Service | Repository URL | Description |
|---------|---------------|-------------|
| **ESA** | [mcp-server-esa](https://github.com/aliyun/mcp-server-esa) | Edge Security Acceleration service |
| **Observability** | [alibabacloud-observability-mcp-server](https://github.com/aliyun/alibabacloud-observability-mcp-server) | Observability service integration |
