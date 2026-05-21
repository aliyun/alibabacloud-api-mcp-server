# Alibaba Cloud OpenAPI MCP Server

## [README of Chinese](README.md)

## 📚 Table of Contents

- [Overview](#overview)
- [Technical Specifications](#technical-specifications)
- [Access Endpoints](#access-endpoints)
- [System MCP Service List](#system-mcp-service-list)
  - [Infrastructure Management](#infrastructure-management)
  - [Monitoring & Auditing](#monitoring--auditing)
  - [Compliance & Governance](#compliance--governance)
- [Core Capabilities](#core-capabilities)
  - [OpenAPI Customization & Optimization](#openapi-customization--optimization)
  - [Terraform As Tools](#terraform-as-tools)
  - [Multi-Account Support](#multi-account-support)
  - [Custom OAuth](#custom-oauth)
- [Quick Start](#quick-start)
  - [Remote Mode Access](#remote-mode-access)
  - [Access with Local Static Credentials](#access-with-local-static-credentials)
- [Best Practices](#best-practices)
- [Telemetry View](#telemetry-view)
- [Local MCP Servers](#local-mcp-servers)
- [Reference Documentation](#reference-documentation)

## Overview

Alibaba Cloud OpenAPI MCP Server is an officially hosted remote MCP service by Alibaba Cloud that provides seamless integration capabilities for Alibaba Cloud services to AI applications through the Model Context Protocol (MCP). Without local deployment, it covers tens of thousands of Alibaba Cloud OpenAPIs, enabling developers to easily integrate various Alibaba Cloud service capabilities into AI workflows.

We recommend using the **API MCP Server Core** mode. This mode follows a remote CLI pattern, enabling orchestration of the full Alibaba Cloud capability surface with a single-digit number of core tools (covering tens of thousands of OpenAPIs), suitable for scenarios requiring rapid integration and low maintenance costs.

## Technical Specifications

- **Core Mode**: API MCP Server Core (remote CLI mode)
- **Supported Protocols**: SSE (Server-Sent Events), Streamable HTTP
- **Authentication Method**: OAuth 2.0
- **API Count**: Supports tens of thousands of Alibaba Cloud OpenAPIs
- **Deployment Method**: Cloud-hosted, zero maintenance

## Access Endpoints

| Region | Access Endpoint | Applicable Scenarios |
|--------|----------------|---------------------|
| **China Site** | https://api.aliyun.com/mcp | Users in mainland China |
| **International Site** | https://api.alibabacloud.com/mcp | Overseas and international users |

## System MCP Service List

Alibaba Cloud officially provides a series of carefully optimized system MCP services, optimized for specific scenarios:

### Infrastructure Management

| Service Name | Function Description |
|-------------|---------------------|
| **Terraform Provider** | Provides Alibaba Cloud Terraform Provider metadata, supports online validation and runtime capabilities for executing Terraform commands |
| **Quota Center** | Query general quota information for products supported by the Quota Center based on cloud product name, quota description, regional information, etc. |
| **Resource Search** | Supports search and statistics functions for resources with permissions under the current account |

### Monitoring & Auditing

| Service Name | Function Description |
|-------------|---------------------|
| **ActionTrail AI** | Uses AI to flexibly call the ActionTrail LookupEvents interface based on scenarios |
| **Permission Diagnostics** | When API requests are rejected due to lack of permissions, perform permission diagnosis through EncodedDiagnosticMessage |

### Compliance & Governance

| Service Name | Function Description |
|-------------|---------------------|
| **Governance Report** | MCP Server based on GovernanceReport |
| **Config Compliance Pack** | Query compliance pack templates, enable specified compliance packs, query risk overview and risk resource inventory |

## Core Capabilities

### OpenAPI Customization & Optimization

- Modify API descriptions to make them more suitable for AI understanding
- Simplify non-required parameters to reduce calling complexity
- Optimize parameter descriptions to improve AI calling accuracy

### Terraform As Tools

- **HCL Code Integration**: Introduce Terraform HCL code as complete tools
- **Automatic Variable Parsing**: Terraform variables automatically convert to tool parameters
- **Deterministic Orchestration**: Achieve deterministic deployment and management of infrastructure

### Multi-Account Support

- **Role Assumption**: Automatically use role assumption capabilities to operate specific accounts
- **Account Switching**: Flexibly specify operation accounts and assumed roles
- **Centralized Management**: Easily achieve multi-account AI integrated management

### Custom OAuth

- **Callback Whitelist**: Precisely control callback address whitelist
- **Token Lifecycle**: Flexibly set access token and refresh token expiration times
- **Long-term Login-free**: Achieve up to 1 year of login-free operation

## Quick Start

### Remote Mode Access

1. **Access Console**
   - China Site users visit: https://api.aliyun.com/mcp
   - International Site users visit: https://api.alibabacloud.com/mcp

2. **OAuth Authentication**
   - Configure OAuth application
   - Obtain Access Token
   - Configure Token refresh strategy

3. **Select Services**
   - Browse system MCP services
   - Select required OpenAPI
   - Customize API parameters

### Access with Local Static Credentials

Alibaba Cloud API MCP Server now supports direct login through local static credentials. You can configure an Alibaba Cloud AccessKey or an existing local credential profile, then use Alibaba Cloud MCP Proxy to automatically exchange it for the token required by OpenAPI MCP Server. This removes the need to manually maintain OAuth tokens in MCP client configuration.

For proxy installation, MCP client configuration, safety policies, and pre-check usage, see: [Alibaba Cloud MCP Proxy User Guide](README-PROXY-EN.md).

## Best Practices

- 📘 [OpenAPI MCP Server Core Best Practices](docs/best-practices-en.md): Learn how to combine `Skill` and `safety policy` with MCP Server Core to build an efficient, secure, and production-ready Agent integration solution.

## Telemetry View

MCP Proxy includes a built-in `telemetry-view` sub-command that launches a local web server to browse plugin telemetry trace data, featuring session lists, span hierarchy tree, Timeline / Graph dual views, fullscreen browsing, and real-time updates.

```bash
uvx alibabacloud.mcp-proxy@latest telemetry-view
```

For details, see [Proxy User Guide - Telemetry View](README-PROXY-EN.md#telemetry-view).

## Local MCP Servers

In addition to the recommended remote OpenAPI MCP Server, we also provide a set of local stdio-based MCP Servers deployed independently by product, suitable for scenarios with high data security requirements or the need for custom configuration.

👉 [View the full list of Local MCP Servers](docs/local-mcp-servers-en.md)

## Reference Documentation

- 📖 **Official Documentation**: [OpenAPI MCP Server User Guide](https://www.alibabacloud.com/help/en/openapi/user-guide/openapi-mcp-server-guide)
- 🔧 **Technical Support**: Get technical support through Alibaba Cloud ticket system or official forums
- 💬 **Community Exchange**: Join the Alibaba Cloud Developer Community for discussions, DingTalk Group: 136325002292

---

*This document is continuously updated. Welcome to submit Issues or PRs to contribute content*
