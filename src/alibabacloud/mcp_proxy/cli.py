from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anyio

from alibabacloud.mcp_proxy.auth.ims_access_token import DEFAULT_IMS_CLIENT_ID
from alibabacloud.mcp_proxy.auth.token_provider import (
    TokenAcquisitionError,
    build_token_provider,
)
from alibabacloud.mcp_proxy.config import AlibabaCloudProxyConfig, ProxyConfigurationError, SiteType
from alibabacloud.mcp_proxy.discovery import discover_mcp_server_url
from alibabacloud.mcp_proxy.precheck import run_precheck
from alibabacloud.mcp_proxy.proxy.server import AlibabaCloudMcpProxyServer
from alibabacloud.mcp_proxy.session.reconnecting_session import ReconnectingSession
from alibabacloud.mcp_proxy.transport.upstream_http import StreamableHttpConnectionFactory
from alibabacloud.mcp_proxy.transport.upstream_sse import SseConnectionFactory

# Mapping for the `server plugin-telemetry` sub-command:
#   (argparse_dest, payload_key, is_required)
# The CLI flag is the kebab-case form of the dest (e.g. start_timestamp ->
# --start-timestamp). Required fields mirror the OpenAPI schema; optional
# fields are forwarded only when the user supplies them.
_PLUGIN_TELEMETRY_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("client_name", "clientName", True),
    ("event_type", "eventType", True),
    ("start_timestamp", "startTimestamp", True),
    ("tool_name", "toolName", True),
    ("session_id", "sessionId", True),
    ("status", "status", True),
    ("end_timestamp", "endTimestamp", False),
    ("turn", "turn", False),
    ("mcp_tool", "mcpTool", False),
    ("cli_command", "cliCommand", False),
    ("query_summary", "querySummary", False),
    ("skill_name", "skillName", False),
    ("tool_request_id", "toolRequestId", False),
    ("error_message", "errorMessage", False),
    ("plugin_name", "pluginName", False),
    ("span_id", "spanId", False),
    ("parent_span_id", "parentSpanId", False),
    ("skill_tag", "skillTag", False),
    ("input_uncached_tokens", "inputUncachedTokens", False),
    ("input_cached_tokens", "inputCachedTokens", False),
    ("input_creation_tokens", "inputCreationTokens", False),
    ("output_tokens", "outputTokens", False),
    ("reasoning_tokens", "reasoningTokens", False),
)

_LOGGER = logging.getLogger(__name__)


def _configure_logging(*, debug: bool, log_file: str | None) -> Path | None:
    """Configure logging based on the --debug flag.

    When *debug* is ``False`` (default), logging is effectively silenced
    (level ``CRITICAL``) so that nothing leaks into stderr — MCP uses
    stdout for JSON-RPC and any stray output would corrupt the protocol
    stream.

    When *debug* is ``True``, the level is set to ``DEBUG`` and logs are
    written to the user-specified *log_file*.  The caller must ensure
    *log_file* is not ``None`` before calling with ``debug=True``.
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.handlers.clear()

    if not debug:
        root.setLevel(logging.CRITICAL)
        return None

    level = logging.DEBUG
    root.setLevel(level)

    log_path = Path(log_file)  # type: ignore[arg-type]
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:
        print(
            f"Error: cannot open log file {log_path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    return log_path

def _add_proxy_arguments(parser: argparse.ArgumentParser) -> None:
    """Add all proxy-related CLI arguments to *parser*."""
    parser.add_argument("--server-url", help="Upstream Alibaba Cloud MCP streamable HTTP URL.")
    parser.add_argument(
        "--site-type",
        dest="site_type",
        choices=["CN", "INTL"],
        default=None,
        help="Alibaba Cloud site type: CN (China, default) or INTL (International).",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        dest="connect_timeout_seconds",
        help="HTTP connect timeout in seconds.",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        dest="read_timeout_seconds",
        help="HTTP read timeout in seconds.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Enable debug logging. Requires --log-file to be set.",
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        default=None,
        help="Path to the log file. Required when --debug is enabled.",
    )
    parser.add_argument(
        "--bearer-token",
        dest="bearer_token",
        help="Explicit bearer token for the upstream MCP server.",
    )
    parser.add_argument(
        "--token-command",
        dest="token_command",
        help="Command that prints a bearer token or JSON with access_token.",
    )
    parser.add_argument(
        "--client-id",
        dest="ims_client_id",
        help="IMS GenerateAccessToken ClientId. "
        f"Default {DEFAULT_IMS_CLIENT_ID} or ALIBABACLOUD_MCP_CLIENT_ID.",
    )
    parser.add_argument(
        "--scope",
        dest="ims_scope",
        help="IMS GenerateAccessToken Scope. "
        "Default /internal/acs/openapi or ALIBABACLOUD_MCP_SCOPE.",
    )
    parser.add_argument(
        "--ims-endpoint",
        dest="ims_endpoint",
        help="IMS API endpoint hostname. Default ramoauth.aliyuncs.com (CN) / ramoauth.alibabacloudcs.com (INTL), or ALIBABACLOUD_MCP_IMS_ENDPOINT.",
    )
    parser.add_argument(
        "--safety-policy",
        dest="safety_policy",
        help="Safety policy expression to constrain allowed MCP tool calls "
        "(e.g. 'ecs:describe-*=allow,*=deny'). "
        "Also settable via ALIBABACLOUD_MCP_SAFETY_POLICY.",
    )
    parser.add_argument(
        "--retry-max-attempts",
        dest="max_attempts",
        type=int,
        help="Maximum attempts per upstream request before surfacing an error.",
    )
    parser.add_argument(
        "--retry-base-seconds",
        dest="base_delay_seconds",
        type=float,
        help="Initial retry delay in seconds.",
    )
    parser.add_argument(
        "--retry-max-seconds",
        dest="max_delay_seconds",
        type=float,
        help="Maximum retry delay in seconds.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alibabacloud.mcp-proxy",
        description="Local stdio MCP proxy for Alibaba Cloud OpenAPI MCP servers.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- default proxy sub-command (also works without a sub-command) ---
    proxy_parser = subparsers.add_parser(
        "proxy",
        help="Run the MCP proxy server (default when no sub-command is given).",
    )
    _add_proxy_arguments(proxy_parser)

    # Also add proxy arguments to the root parser so that the tool works
    # without an explicit "proxy" sub-command (backward compatibility).
    _add_proxy_arguments(parser)

    # --- pre-check sub-command ---
    precheck_parser = subparsers.add_parser(
        "pre-check",
        help="Verify OAuth app installation by running a local callback server.",
    )
    precheck_parser.add_argument(
        "--site-type",
        dest="site_type",
        choices=["CN", "INTL"],
        default=None,
        help="Alibaba Cloud site type: CN (China, default) or INTL (International).",
    )
    precheck_parser.add_argument(
        "--client-id",
        dest="oauth_client_id",
        default=None,
        help="Custom OAuth application Client ID. "
        "If not specified, the default for the chosen site type is used.",
    )

    # --- plugin-telemetry sub-command ---
    plugin_telemetry_parser = subparsers.add_parser(
        "plugin-telemetry",
        help="Send a telemetry event to the Alibaba Cloud OpenAPI backend.",
    )
    _add_plugin_telemetry_arguments(plugin_telemetry_parser)

    # --- telemetry-view sub-command ---
    telemetry_view_parser = subparsers.add_parser(
        "telemetry-view",
        help="Launch local web UI to browse telemetry traces.",
    )
    telemetry_view_parser.add_argument(
        "--port", type=int, default=18321, dest="tv_port",
        help="Local server port (default: 18321).",
    )
    telemetry_view_parser.add_argument(
        "--no-open", action="store_true", dest="tv_no_open",
        help="Don't auto-open browser.",
    )

    return parser


def _add_plugin_telemetry_arguments(parser: argparse.ArgumentParser) -> None:
    """Add CLI flags for `server plugin-telemetry` (kebab → camelCase mapping)."""
    # ── required fields ───────────────────────────────────────────────────
    parser.add_argument("--client-name", dest="client_name", required=True,
                        help="Originating client name, e.g. 'claude-code'.")
    parser.add_argument("--event-type", dest="event_type", required=True,
                        help="Telemetry event type, e.g. 'tool_call', 'skill_invocation'.")
    parser.add_argument(
        "--start-timestamp", "--timestamp",
        dest="start_timestamp", required=True,
        help="Event start time (ISO-8601). '--timestamp' is accepted as an alias.",
    )
    parser.add_argument("--tool-name", dest="tool_name", required=True,
                        help="Name of the tool being reported on.")
    parser.add_argument("--session-id", dest="session_id", required=True,
                        help="Caller-defined session identifier.")
    parser.add_argument("--status", dest="status", required=True,
                        help="Outcome status, e.g. 'success', 'failure'.")
    # ── optional fields ───────────────────────────────────────────────────
    parser.add_argument("--end-timestamp", dest="end_timestamp",
                        help="Event end time (ISO-8601).")
    parser.add_argument("--turn", dest="turn", type=int,
                        help="Conversational turn number (int32).")
    parser.add_argument("--mcp-tool", dest="mcp_tool", help="MCP tool identifier.")
    parser.add_argument("--cli-command", dest="cli_command", help="Issued CLI command, if any.")
    parser.add_argument("--query-summary", dest="query_summary", help="Short summary of the user query.")
    parser.add_argument("--skill-name", dest="skill_name", help="Skill name, if applicable.")
    parser.add_argument("--tool-request-id", dest="tool_request_id", help="Caller's tool request id.")
    parser.add_argument("--error-message", dest="error_message", help="Error message when status='failure'.")
    parser.add_argument("--plugin-name", dest="plugin_name", help="Plugin name, e.g. 'alibabacloud'.")
    parser.add_argument("--span-id", dest="span_id", help="Trace span identifier.")
    parser.add_argument("--parent-span-id", dest="parent_span_id", help="Parent trace span identifier.")
    parser.add_argument("--skill-tag", dest="skill_tag",
                        help="Skill tag inferred from the tool input path.")
    parser.add_argument("--input-uncached-tokens", dest="input_uncached_tokens", type=int,
                        help="LLM input tokens not served from cache (int32).")
    parser.add_argument("--input-cached-tokens", dest="input_cached_tokens", type=int,
                        help="LLM input tokens served from cache (int32).")
    parser.add_argument("--input-creation-tokens", dest="input_creation_tokens", type=int,
                        help="LLM input tokens consumed creating cache entries (int32).")
    parser.add_argument("--output-tokens", dest="output_tokens", type=int,
                        help="LLM output tokens (int32).")
    parser.add_argument("--reasoning-tokens", dest="reasoning_tokens", type=int,
                        help="LLM reasoning output tokens (int32).")
    # ── operational flags ─────────────────────────────────────────────────
    parser.add_argument("--verbose", action="store_true",
                        help="Log INFO+ to stderr (default: WARNING+).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress all logging.")


def parse_config(
    args: argparse.Namespace | Sequence[str] | None = None,
) -> AlibabaCloudProxyConfig:
    """Build a proxy config from parsed args or a raw argv list.

    Accepts either an already-parsed ``argparse.Namespace`` **or** a raw
    argument list (``Sequence[str]`` / ``None``) for backward compatibility
    with tests and callers that pass ``sys.argv``-style lists.
    """
    if not isinstance(args, argparse.Namespace):
        args = build_parser().parse_args(args)

    values = {
        "site_type": args.site_type,
        "server_url": args.server_url,
        "connect_timeout_seconds": _stringify(args.connect_timeout_seconds),
        "read_timeout_seconds": _stringify(args.read_timeout_seconds),
        "debug": _stringify(args.debug),
        "log_file": args.log_file,
        "bearer_token": args.bearer_token,
        "token_command": args.token_command,
        "safety_policy": args.safety_policy,
        "ims_client_id": args.ims_client_id,
        "ims_scope": args.ims_scope,
        "ims_endpoint": args.ims_endpoint,
        "max_attempts": _stringify(args.max_attempts),
        "base_delay_seconds": _stringify(args.base_delay_seconds),
        "max_delay_seconds": _stringify(args.max_delay_seconds),
    }
    return AlibabaCloudProxyConfig.from_mapping(
        values,
        defaults=AlibabaCloudProxyConfig.env_values(),
    )


def _is_sse_endpoint(server_url: str) -> bool:
    """Return True if the server URL indicates an SSE transport (ends with /sse)."""
    return server_url.rstrip("/").endswith("/sse")

async def _resolve_server_url(config: AlibabaCloudProxyConfig) -> str:
    """Return the MCP server URL, discovering it via OpenAPI if not explicitly set."""
    if config.server_url:
        _LOGGER.info("Using user-specified server URL: %s", config.server_url)
        return config.server_url

    return await discover_mcp_server_url(config.site_type)


async def run_proxy(config: AlibabaCloudProxyConfig) -> None:
    server_url = await _resolve_server_url(config)
    token_provider = build_token_provider(config.token)

    if _is_sse_endpoint(server_url):
        connection_factory = SseConnectionFactory(config, server_url)
    else:
        connection_factory = StreamableHttpConnectionFactory(config, server_url)

    async with anyio.create_task_group() as background_tasks:
        connection_factory.set_task_group(background_tasks)
        session = ReconnectingSession(
            connection_factory,
            token_provider,
            config.retry,
            safety_policy=config.token.safety_policy,
        )
        proxy = AlibabaCloudMcpProxyServer(config, session)
        try:
            await proxy.run()
        finally:
            await proxy.aclose()
            background_tasks.cancel_scope.cancel()


def _resolve_site_type(raw: str | None) -> SiteType:
    """Parse a raw site-type string into a ``SiteType`` enum, defaulting to CN."""
    normalized = (raw or "").strip().upper() or "CN"
    try:
        return SiteType(normalized)
    except ValueError:
        print(f"Error: Invalid site type '{raw}'. Must be CN or INTL.", file=sys.stderr)
        raise SystemExit(1)


def _run_precheck_command(args: argparse.Namespace) -> int:
    """Execute the ``pre-check`` sub-command."""
    site_type = _resolve_site_type(args.site_type)
    client_id = getattr(args, "oauth_client_id", None)
    return run_precheck(site_type, client_id=client_id)


def _run_proxy_command(args: argparse.Namespace) -> int:
    """Execute the proxy (default) command."""
    try:
        config = parse_config(args)
    except (ProxyConfigurationError, TokenAcquisitionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(str(exc)) from exc

    if config.debug and not config.log_file:
        print(
            "Error: --debug requires --log-file to be specified.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    log_path = _configure_logging(debug=config.debug, log_file=config.log_file)

    if config.debug:
        _LOGGER.info(
            "stdio MCP server starting — debug logging enabled, writing to %s. "
            "Site type: %s. Process will wait until an MCP client connects.",
            log_path,
            config.site_type.value,
        )

    try:
        anyio.run(run_proxy, config)
    except (ProxyConfigurationError, TokenAcquisitionError) as exc:
        if config.debug:
            _LOGGER.exception("Proxy terminated with configuration/token error: %s", exc)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(str(exc)) from exc
    return 0


def _build_telemetry_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Translate parsed CLI args into the schema-compliant JSON payload."""
    payload: dict[str, Any] = {}
    for cli_attr, payload_key, _ in _PLUGIN_TELEMETRY_FIELDS:
        value = getattr(args, cli_attr, None)
        if value is None:
            continue
        if isinstance(value, str) and not value:
            # Skip empty optional strings; the backend treats absence and "" the same
            # way and dropping them keeps logs cleaner.
            if payload_key in {"clientName", "eventType", "startTimestamp",
                                "toolName", "sessionId", "status"}:
                payload[payload_key] = value  # honor required-but-empty literally
            continue
        payload[payload_key] = value
    return payload


def _configure_oneshot_logging(args: argparse.Namespace) -> None:
    """Configure logging for one-shot CLI commands (writes to stderr)."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.handlers.clear()

    if getattr(args, "quiet", False):
        root.setLevel(logging.CRITICAL)
        return

    level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(fmt)
    root.addHandler(handler)


def _run_telemetry_view_command(args: argparse.Namespace) -> int:
    """Execute the ``telemetry-view`` sub-command."""
    import asyncio
    from alibabacloud.mcp_proxy.telemetry_view import run_telemetry_view

    try:
        asyncio.run(run_telemetry_view(port=args.tv_port, no_open=args.tv_no_open))
    except KeyboardInterrupt:
        pass
    return 0


def _run_plugin_telemetry_command(args: argparse.Namespace) -> int:
    """Execute `server plugin-telemetry`: build payload, POST it, surface result."""
    # Local import keeps the proxy startup path free from any telemetry imports.
    from alibabacloud.mcp_proxy.telemetry import report_telemetry

    _configure_oneshot_logging(args)
    payload = _build_telemetry_payload(args)

    try:
        response = report_telemetry(payload)
    except Exception as exc:  # noqa: BLE001 - hard safety net; should never trigger
        print(f"Error: telemetry call raised unexpectedly: {exc}", file=sys.stderr)
        return 1

    if response is None:
        # report_telemetry has already logged the failure detail.
        return 1

    body = response.get("body") if isinstance(response, dict) else None
    if isinstance(body, dict) and body.get("success") is False:
        print(f"Telemetry rejected by backend: {body}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "pre-check":
        return _run_precheck_command(args)

    if args.command == "plugin-telemetry":
        return _run_plugin_telemetry_command(args)

    if args.command == "telemetry-view":
        return _run_telemetry_view_command(args)

    # Default: run the proxy (covers both explicit "proxy" and no sub-command)
    return _run_proxy_command(args)


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
