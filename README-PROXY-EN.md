## Alibaba Cloud MCP Proxy

A local stdio MCP (Model Context Protocol) proxy for Alibaba Cloud OpenAPI MCP servers. It bridges MCP clients (such as Claude Desktop, Cursor, or other AI-powered IDEs) with Alibaba Cloud's upstream MCP services, handling authentication, connection management, retries, and safety policies transparently.

### Prerequisites

The RAM user or role running the proxy **must** have the following permissions. Attach this policy in the [RAM Console](https://ram.console.aliyun.com/):

Alibaba Cloud provides a built-in system policy named `AliyunOpenAPIMCPServerStaticCredentialAccess` (full Access policy for static-credential connection).

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

- **`ram:GenerateAccessToken`** — Required for the proxy to obtain bearer tokens via IMS.
- **`openapiexplorer:*`** — Required for MCP server discovery and tool invocation.

### Quick Start

Run the proxy with `uvx` (always fetches the latest version, no install needed):

```bash
uvx alibabacloud.mcp-proxy@latest
```

If you have a custom MCP server URL, you can specify it explicitly:

```bash
uvx alibabacloud.mcp-proxy@latest --server-url <YOUR_MCP_SERVER_URL>
```

#### MCP Client Configuration (Claude Desktop / Cursor)

Add the following to your MCP client configuration file (e.g. `claude_desktop_config.json`):

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

The proxy reads local Alibaba Cloud static credentials and automatically exchanges them for the access token required by the upstream OpenAPI MCP Server.

### Local Static Credential Login

Alibaba Cloud API MCP Server now supports direct login through local static credentials. You can configure credentials with Alibaba Cloud CLI or environment variables, and MCP Proxy will read them locally and call IMS `GenerateAccessToken` to obtain a Bearer Token. This removes the need to manually manage OAuth tokens in MCP client configuration.

Common environment variable configuration:

```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key_id
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_access_key_secret
uvx alibabacloud.mcp-proxy@latest
```

### Debugging

To enable debug logging, use `--debug` together with `--log-file` to write detailed logs to a file:

```bash
uvx alibabacloud.mcp-proxy@latest --debug --log-file=/tmp/a.log --safety-policy "ecs:describe-*=allow,*=deny"
```

### Safety Policy

You can constrain which MCP tools the proxy is allowed to invoke by specifying a **safety policy**. This is applied to the bearer token before connecting to the upstream MCP server, ensuring the token is scoped to only the allowed tool calls.

#### Example: Allow only ECS describe operations

```bash
uvx alibabacloud.mcp-proxy@latest --safety-policy "ecs:describe-*=allow,*=deny"
```

#### MCP Client Configuration with Safety Policy

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

You can also set the safety policy via environment variable:

```bash
export ALIBABACLOUD_MCP_SAFETY_POLICY="ecs:describe-*=allow,*=deny"
uvx alibabacloud.mcp-proxy@latest
```

### Pre-check (Optional)

When using the default Client ID, there is no need to run a separate pre-check — the proxy handles authentication automatically.

If you specify a custom `--client-id`, you can use the **pre-check** command to verify that the OAuth application is properly installed and authorized:

```bash
uvx alibabacloud.mcp-proxy@latest pre-check --client-id YOUR_OAUTH_CLIENT_ID
```

For international sites:

```bash
uvx alibabacloud.mcp-proxy@latest pre-check --client-id YOUR_OAUTH_CLIENT_ID --site-type INTL
```

If the pre-check passes, you will see:

```
✓ Pre-check passed! You can connect via local static credentials.
```

### Plugin Telemetry

To help us continuously improve MCP Proxy stability and identify common error patterns, this tool ships an opt-in `plugin-telemetry` sub-command that **callers explicitly invoke** to report the trace of a single operation. The sub-command is **optional and explicitly triggered** — if you never call it, no telemetry data is ever transmitted. There is no passive collection in any other sub-command (`proxy`, `pre-check`).

#### Usage

```bash
uvx alibabacloud.mcp-proxy@latest plugin-telemetry \
  --client-name "claude-code" \
  --event-type "mcp_tool_use" \
  --start-timestamp "2026-05-18T10:30:00Z" \
  --tool-name "AlibabaCloud___CallCLI" \
  --session-id "<anonymous-session-id>" \
  --status "success" \
  --span-id "span-abc123" \
  --parent-span-id "span-root-000"
```

#### Fields & Sanitization Guidance

| Flag | Required | Purpose | Safe to send as-is? |
|------|:--------:|---------|--------------------|
| `--client-name` | ✅ | Caller identifier (e.g. `claude-code`) | ✅ Yes |
| `--event-type` | ✅ | Event category (e.g. `tool_call`, `skill_invocation`) | ✅ Yes |
| `--start-timestamp` | ✅ | Start time (ISO-8601) | ✅ Yes |
| `--end-timestamp` |   | End time | ✅ Yes |
| `--tool-name` | ✅ | Tool name | ✅ Yes |
| `--session-id` | ✅ | Session id | ⚠️ **Must be anonymized.** Use a caller-generated UUID. |
| `--status` | ✅ | Outcome (`success` / `failure`) | ✅ Yes |
| `--turn` |   | Turn number | ✅ Yes |
| `--mcp-tool` |   | MCP tool identifier | ✅ Yes |
| `--skill-name` |   | Skill name | ✅ Yes |
| `--plugin-name` |   | Plugin name | ✅ Yes |
| `--tool-request-id` |   | Caller-generated UUID | ✅ Yes |
| `--span-id` |   | Current span identifier (for distributed tracing) | ✅ Yes |
| `--parent-span-id` |   | Parent span identifier (to build the call tree) | ✅ Yes |
| `--cli-command` |   | CLI command line | ⚠️ **Sanitize**: keep the command shape; strip IDs, credentials, file paths from the arguments. |
| `--query-summary` |   | Query summary | ⚠️ **Sanitize**: keep an intent category, do **not** copy the raw user prompt. |
| `--error-message` |   | Error message | ⚠️ **Sanitize**: keep the error class/code; strip tokens, access keys, IPs, internal hostnames. |

#### Privacy Notice (Customer)

- **Purpose of collection.** Telemetry data is used solely to analyze MCP Proxy usage patterns, error rates, and performance bottlenecks. It is **not** linked to any business resources under your account and is **not** used for commercial purposes.
- **Design principle: necessary action + outcome status only — never sensitive data.** Do not put the following into free-text fields (`--cli-command`, `--query-summary`, `--error-message`, etc.):
  - Alibaba Cloud AccessKey, SecurityToken, Bearer Token, OAuth code
  - Real names / phone numbers / emails / ID numbers of users or RAM sub-accounts
  - Database passwords, private keys, certificate contents, private endpoints
  - Personally Identifiable Information (PII), internal IPs / hostnames
  - Customer data covered by compliance regimes (GDPR, PIPL, HIPAA, ...)
- **Sanitize before calling.** If you're unsure whether a string is safe, run it through a redactor before passing it to the CLI: replace `(?i)ak[a-z0-9]{16,}`, `/Users/[^/]+/`, emails, phone numbers, and UUIDs with placeholders.
- **Opt-out is implicit.** Don't invoke `plugin-telemetry` and no data leaves your machine.

#### Failure Behavior

`plugin-telemetry` is best-effort: 4 attempts max, 3-second connect/read timeout per attempt. Failures only print WARN/ERROR to stderr — they never raise exceptions or disrupt the calling process. Exit codes: `0` success / `1` reporting failed after all retries / `2` argument error.

### Telemetry View

The `telemetry-view` sub-command launches a local web server for browsing and analyzing plugin telemetry trace data. It supports multiple clients (Claude Code, VS Code, Copilot CLI, Codex, Qoderwork) with session browsing, span hierarchy tree, Gantt timeline, Graph flow view, and real-time updates.

#### Launch

```bash
uvx alibabacloud.mcp-proxy@latest telemetry-view
```

By default it starts on `http://localhost:18321` and opens the browser automatically.

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `18321` | Local server port |
| `--no-open` | - | Don't auto-open browser |

#### Data Sources

Automatically scans JSONL trace files from:

1. `$ALIBABACLOUD_TELEMETRY_STATE_DIR` (if set)
2. `~/.cache/alibabacloud-agent-toolkit/telemetry/`
3. `/tmp/alibabacloud-agent-toolkit-telemetry-<uid>/`

#### Features

- **Home page**: Lists all sessions with client filter, keyword search, time range filter; top stats bar shows total sessions, per-client distribution, and success rate
- **Trace detail page**:
  - Left: collapsible span tree. Right: switchable Timeline (Gantt bars) and Graph (turn-grouped flow diagram) views
  - Graph supports mouse wheel zoom, drag-to-pan, fullscreen mode; clicking nodes in fullscreen shows a floating detail tooltip
  - Clicking any span shows full detail (event type, tool name, duration, status, input/output, etc.)
- **Real-time updates**: New spans are pushed via SSE without manual refresh
- **Dark/light theme toggle**

### Configuration Reference

Every CLI flag has a corresponding environment variable. **CLI flags take precedence** over environment variables.

#### Connection Settings

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--server-url` | `ALIBABACLOUD_MCP_SERVER_URL` | *(auto-discover)* | Upstream Alibaba Cloud MCP streamable HTTP URL. If not set, the proxy discovers it via the `ListApiMcpServerCores` OpenAPI. |
| `--site-type` | `ALIBABACLOUD_MCP_SITE_TYPE` | `CN` | Alibaba Cloud site type: `CN` (China) or `INTL` (International). |
| `--connect-timeout` | `ALIBABACLOUD_MCP_CONNECT_TIMEOUT` | `10.0` | HTTP connect timeout in seconds. |
| `--read-timeout` | `ALIBABACLOUD_MCP_READ_TIMEOUT` | `120.0` | HTTP read timeout in seconds. |

#### Authentication Settings

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--bearer-token` | `ALIBABACLOUD_MCP_BEARER_TOKEN` | — | Explicit bearer token for the upstream MCP server. |
| `--token-command` | `ALIBABACLOUD_MCP_TOKEN_COMMAND` | — | Shell command that prints a bearer token or JSON with `access_token`. |
| `--client-id` | `ALIBABACLOUD_MCP_CLIENT_ID` | *(per site type)* | IMS `GenerateAccessToken` ClientId. Defaults to `4071151845732613353` (CN) or `4195410055503316452` (INTL). |
| `--scope` | `ALIBABACLOUD_MCP_SCOPE` | `/internal/acs/openapi` | IMS `GenerateAccessToken` Scope. |
| `--ims-endpoint` | `ALIBABACLOUD_MCP_IMS_ENDPOINT` | `ramoauth.aliyuncs.com` (CN) / `ramoauth.alibabacloudcs.com` (INTL) | IMS API endpoint hostname. Auto-selected based on `--site-type`. |

#### Safety Policy

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--safety-policy` | `ALIBABACLOUD_MCP_SAFETY_POLICY` | — | Safety policy expression to constrain allowed MCP tool calls (e.g. `ecs:describe-*=allow,*=deny`). Applied to the bearer token before connecting. |

#### Retry Settings

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--retry-max-attempts` | `ALIBABACLOUD_MCP_RETRY_MAX_ATTEMPTS` | `3` | Maximum attempts per upstream request before surfacing an error. |
| `--retry-base-seconds` | `ALIBABACLOUD_MCP_RETRY_BASE_SECONDS` | `1.0` | Initial retry delay in seconds (exponential backoff). |
| `--retry-max-seconds` | `ALIBABACLOUD_MCP_RETRY_MAX_SECONDS` | `8.0` | Maximum retry delay in seconds. |

#### Token Refresh

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| — | `ALIBABACLOUD_MCP_REFRESH_SKEW_SECONDS` | `60` | Seconds before token expiry to trigger a proactive refresh. |

#### Debug / Logging

| CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--debug` | `ALIBABACLOUD_MCP_DEBUG` | `false` | Enable debug logging. Requires `--log-file` to be set. |
| `--log-file` | `ALIBABACLOUD_MCP_LOG_FILE` | — | Path to the log file. Required when `--debug` is enabled. |

#### Pre-check Sub-command

| CLI Flag | Default | Description |
|---|---|---|
| `--site-type` | `CN` | Alibaba Cloud site type: `CN` or `INTL`. |
| `--client-id` | *(per site type)* | Custom OAuth application Client ID for the pre-check flow. |

### Requirements

- Python >= 3.13

### License

Apache-2.0
