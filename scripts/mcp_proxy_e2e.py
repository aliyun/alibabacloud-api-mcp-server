#!/usr/bin/env python3
"""Run local Proxy -> remote CloudSpec MCP dual-era acceptance checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, METHOD_NOT_FOUND

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup  # type: ignore[no-redef]

RUNSCRIPT_TOOL = "AlibabaCloud___RunScript"
GET_TASK_TOOL = "AlibabaCloud___GetTask"

READONLY_TOOL_CASES = (
    (
        "AlibabaCloud___ListProducts",
        {"filter": "Ecs"},
    ),
    (
        "AlibabaCloud___ListApis",
        {
            "product": "Ecs",
            "apiVersion": "2014-05-26",
            "filter": "DescribeRegions",
            "includeApiDefinition": False,
        },
    ),
    (
        "AlibabaCloud___ListProductRegions",
        {"product": "Ecs"},
    ),
    (
        "AlibabaCloud___GetApiDefinition",
        {
            "product": "Ecs",
            "apiVersion": "2014-05-26",
            "apiName": "DescribeRegions",
        },
    ),
)

ALL_TOOL_STATIC_CASES = (
    (
        "AlibabaCloud___SearchApis",
        {
            "prompt": "List the Alibaba Cloud API for querying ECS regions",
            "limit": 1,
        },
    ),
    (
        "AlibabaCloud___CallCLI",
        {"command": "aliyun ecs DescribeRegions"},
    ),
    (
        "AlibabaCloud___GetApiDefinition",
        {
            "product": "Ecs",
            "apiVersion": "2014-05-26",
            "apiName": "DescribeRegions",
        },
    ),
    (
        "AlibabaCloud___ListApis",
        {
            "product": "Ecs",
            "apiVersion": "2014-05-26",
            "filter": "DescribeRegions",
            "includeApiDefinition": False,
        },
    ),
    (
        "AlibabaCloud___ListProductRegions",
        {"product": "Ecs"},
    ),
    (
        "AlibabaCloud___GenerateCLICommand",
        {
            "product": "Ecs",
            "apiVersion": "2014-05-26",
            "apiName": "DescribeRegions",
        },
    ),
    (
        "AlibabaCloud___ListProducts",
        {"filter": "Ecs"},
    ),
    (
        "AlibabaCloud___SearchDocuments",
        {
            "query": "ECS 地域和可用区",
            "product": "ecs",
            "limit": 1,
            "website": "cn",
            "language": "zh",
        },
    ),
    (
        "AlibabaCloud___GetDocumentTree",
        {
            "product": "ecs",
            "depth": 1,
            "website": "cn",
            "language": "zh",
        },
    ),
    (
        "AlibabaCloud___GrepDocuments",
        {
            "product": "ecs",
            "pattern": "实例",
            "limit": 1,
            "website": "cn",
            "language": "zh",
        },
    ),
    (
        "AlibabaCloud___GetPresignedUrl",
        {
            "requests": [
                {
                    "operation": "upload",
                    "expires_in": 60,
                }
            ]
        },
    ),
)

EXPECTED_PREPROD_TOOL_NAMES = (
    "AlibabaCloud___SearchApis",
    "AlibabaCloud___CallCLI",
    "AlibabaCloud___GetApiDefinition",
    "AlibabaCloud___ListApis",
    "AlibabaCloud___ListProductRegions",
    "AlibabaCloud___GenerateCLICommand",
    "AlibabaCloud___ListProducts",
    "AlibabaCloud___SearchDocuments",
    "AlibabaCloud___GetDocument",
    "AlibabaCloud___GetDocumentTree",
    "AlibabaCloud___GrepDocuments",
    "AlibabaCloud___GetPresignedUrl",
    RUNSCRIPT_TOOL,
    GET_TASK_TOOL,
    "AlibabaCloud___RunIaC",
)

RUNSCRIPT_SOURCE = (
    "result = await call_cli(product='Ecs', version='2014-05-26', "
    "action='DescribeRegions', params={})"
)

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

_SECRET_KEY_FRAGMENTS = {
    "authorization",
    "accesskeyid",
    "accesskeysecret",
    "secretaccesskey",
    "securitytoken",
    "bearertoken",
    "temporaryaccesskey",
    "tmpak",
}

_CREDENTIAL_ENV_NAMES = (
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "ALIBABA_CLOUD_SECURITY_TOKEN",
    "ALIBABACLOUD_MCP_BEARER_TOKEN",
)


def _normalized_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def sanitize_output(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[object, Any] = {}
        for key, item in value.items():
            normalized = _normalized_key(key)
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitize_output(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_output(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_output(item) for item in value]
    return value


def _redact_error_message(message: str) -> str:
    redacted = message
    for env_name in _CREDENTIAL_ENV_NAMES:
        secret = os.environ.get(env_name)
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _actionable_error_message(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return _actionable_error_message(error.exceptions[0])
    message = str(error).strip()
    return message or type(error).__name__


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    if stripped.startswith("```") and stripped.endswith("```"):
        body = stripped[3:-3].strip()
        if body.startswith("json"):
            body = body[4:].lstrip()
        candidates.append(body)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_result_payload(result: types.CallToolResult) -> dict[str, Any]:
    if isinstance(result.structured_content, dict):
        return result.structured_content

    for content in result.content:
        if isinstance(content, types.TextContent):
            parsed = _parse_json_object(content.text)
            if parsed is not None:
                return parsed

    raise RuntimeError("Tool response did not contain a JSON object payload.")


def extract_process_id(task: dict[str, Any]) -> str:
    process_id = task.get("processID")
    if not isinstance(process_id, str) or not process_id.strip():
        raise RuntimeError("RunScript response did not contain a processID.")
    return process_id


def validate_successful_task(task: dict[str, Any]) -> None:
    process_id = extract_process_id(task)
    status = task.get("status")
    if status != "Succeeded":
        raise RuntimeError(
            f"RunScript failed for processID={process_id}: status={status}"
        )
    if task.get("nextAction") not in (None, "None"):
        raise RuntimeError(
            f"Succeeded task unexpectedly requires a next action: "
            f"{task.get('nextAction')}"
        )
    if task.get("waitTimedOut") is True:
        raise RuntimeError("Succeeded task unexpectedly reports waitTimedOut=true.")
    if not task.get("result"):
        raise RuntimeError(
            "Succeeded task did not contain real call_cli output."
        )


def summarize_completed_task(task: dict[str, Any]) -> dict[str, Any]:
    validate_successful_task(task)
    return {
        "phase": "runscript-complete",
        "processID": extract_process_id(task),
        "status": task.get("status"),
        "nextAction": task.get("nextAction"),
        "waitTimedOut": task.get("waitTimedOut"),
        "resultNonempty": bool(task.get("result")),
    }


def build_server_parameters(args: argparse.Namespace) -> StdioServerParameters:
    repository_root = Path(__file__).resolve().parents[1]
    child_env = os.environ.copy()
    bearer_token_env = args.bearer_token_env
    if bearer_token_env:
        bearer_token = os.environ.get(bearer_token_env)
        if not bearer_token:
            raise RuntimeError(
                f"Bearer token environment variable is not set: "
                f"{bearer_token_env}"
            )
        child_env["ALIBABACLOUD_MCP_BEARER_TOKEN"] = bearer_token

    proxy_args = [
        "-m",
        "alibabacloud.mcp_proxy",
        "--server-url",
        args.server_url,
        "--read-timeout",
        str(args.proxy_read_timeout_seconds),
        "--debug",
        "--log-file",
        args.log_file,
    ]
    return StdioServerParameters(
        command=sys.executable,
        args=proxy_args,
        env=child_env,
        cwd=repository_root,
    )


def print_json(value: Any) -> None:
    print(
        json.dumps(
            sanitize_output(value),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        flush=True,
    )


def summarize_tool_contract(tool: types.Tool) -> dict[str, Any]:
    schema = tool.input_schema
    required = schema.get("required")
    properties = schema.get("properties")
    return {
        "name": tool.name,
        "inputType": schema.get("type"),
        "required": sorted(required) if isinstance(required, list) else [],
        "properties": (
            sorted(properties)
            if isinstance(properties, dict)
            else []
        ),
        "hasOutputSchema": tool.output_schema is not None,
    }


def build_readonly_tool_cases() -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (tool_name, dict(arguments))
        for tool_name, arguments in READONLY_TOOL_CASES
    )


def build_all_tool_static_cases() -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (tool_name, dict(arguments))
        for tool_name, arguments in ALL_TOOL_STATIC_CASES
    )


def validate_expected_tool_surface(tool_names: list[str]) -> None:
    expected = Counter(EXPECTED_PREPROD_TOOL_NAMES)
    actual = Counter(tool_names)
    if actual == expected:
        return
    missing = sorted((expected - actual).elements())
    unexpected = sorted((actual - expected).elements())
    raise RuntimeError(
        "Preprod tool surface differs from the expected 15-tool contract: "
        f"missing={missing}, unexpected={unexpected}"
    )


def build_get_document_arguments(
    search_result: types.CallToolResult,
) -> dict[str, Any]:
    payload = extract_result_payload(search_result)
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError(
            "SearchDocuments did not return a document reference."
        )
    first = results[0]
    if not isinstance(first, dict):
        raise RuntimeError(
            "SearchDocuments did not return a document reference."
        )

    doc_id = first.get("doc_id")
    if isinstance(doc_id, int) and doc_id > 0:
        return {"doc_id": doc_id, "max_length": 1024}
    if isinstance(doc_id, str) and doc_id.isdigit() and int(doc_id) > 0:
        return {"doc_id": int(doc_id), "max_length": 1024}

    url = first.get("url")
    if isinstance(url, str) and url.strip():
        return {"url": url, "max_length": 1024}
    raise RuntimeError(
        "SearchDocuments did not return a document reference."
    )


def summarize_readonly_tool_result(
    tool_name: str,
    result: types.CallToolResult,
) -> dict[str, Any]:
    if result.is_error:
        raise RuntimeError(f"{tool_name} returned isError=true.")

    response_nonempty = bool(result.structured_content)
    if not response_nonempty:
        response_nonempty = any(
            not isinstance(content, types.TextContent)
            or bool(content.text.strip())
            for content in result.content
        )
    if not response_nonempty:
        raise RuntimeError(f"{tool_name} returned an empty response.")

    return {
        "phase": "readonly-tool",
        "tool": tool_name,
        "isError": bool(result.is_error),
        "contentCount": len(result.content),
        "structuredContentType": (
            type(result.structured_content).__name__
            if result.structured_content is not None
            else None
        ),
        "responseNonempty": True,
    }


def summarize_successful_tool_result(
    tool_name: str,
    result: types.CallToolResult,
) -> dict[str, Any]:
    summary = summarize_readonly_tool_result(tool_name, result)
    summary["phase"] = "tool-success"
    return summary


def summarize_runiac_validation_result(
    result: types.CallToolResult,
) -> dict[str, Any]:
    if result.is_error:
        raise RuntimeError(
            "AlibabaCloud___RunIaC returned an MCP tool error instead of "
            "its contract validation result."
        )
    payload = extract_result_payload(result)
    if payload.get("status") != "ValidationFailed" or payload.get("processID"):
        raise RuntimeError(
            "RunIaC did not reject the safe empty request before creating "
            "a process."
        )
    return {
        "phase": "tool-validation",
        "tool": "AlibabaCloud___RunIaC",
        "outcome": "expected-validation-rejection",
        "status": payload.get("status"),
        "nextAction": payload.get("nextAction"),
        "processCreated": False,
    }


async def _run_readonly_tool_smoke(client: Client) -> None:
    for tool_name, arguments in build_readonly_tool_cases():
        result = await client.call_tool(tool_name, arguments)
        print_json(summarize_readonly_tool_result(tool_name, result))


async def _run_all_tools_smoke(
    client: Client,
    args: argparse.Namespace,
) -> None:
    search_result: types.CallToolResult | None = None
    for tool_name, arguments in build_all_tool_static_cases():
        result = await client.call_tool(tool_name, arguments)
        print_json(summarize_successful_tool_result(tool_name, result))
        if tool_name == "AlibabaCloud___SearchDocuments":
            search_result = result

    if search_result is None:
        raise RuntimeError("SearchDocuments was not executed.")
    document_result = await client.call_tool(
        "AlibabaCloud___GetDocument",
        build_get_document_arguments(search_result),
    )
    print_json(
        summarize_successful_tool_result(
            "AlibabaCloud___GetDocument",
            document_result,
        )
    )

    await _run_runscript_smoke(client, args)

    runiac_result = await client.call_tool(
        "AlibabaCloud___RunIaC",
        {},
    )
    print_json(summarize_runiac_validation_result(runiac_result))


async def _run_protocol_behavior_smoke(
    client: Client,
    *,
    mode: str,
) -> None:
    try:
        await client.send_ping()
    except MCPError as error:
        if mode == "legacy":
            raise
        if error.code != METHOD_NOT_FOUND:
            raise
        print_json(
            {
                "phase": "ping",
                "outcome": "expected-rejection",
                "errorCode": error.code,
            }
        )
    else:
        if mode != "legacy":
            raise RuntimeError(
                "Modern proxy unexpectedly accepted removed ping method."
            )
        print_json({"phase": "ping", "outcome": "success"})

    for tool_name, arguments, behavior in (
        (
            "AlibabaCloud___DefinitelyMissing",
            {},
            "unknown-tool",
        ),
        (
            "AlibabaCloud___GetApiDefinition",
            {},
            "invalid-tool-arguments",
        ),
    ):
        try:
            result = await client.call_tool(tool_name, arguments)
        except MCPError as error:
            if error.code not in (INVALID_PARAMS, METHOD_NOT_FOUND):
                raise
            print_json(
                {
                    "phase": behavior,
                    "tool": tool_name,
                    "outcome": "expected-rejection",
                    "errorCode": error.code,
                }
            )
            continue
        if not result.is_error:
            raise RuntimeError(
                f"{behavior} unexpectedly returned isError=false."
            )
        print_json(
            {
                "phase": behavior,
                "tool": tool_name,
                "outcome": "expected-rejection",
            }
        )

    surface_calls = (
        ("prompts/list", client.list_prompts),
        ("resources/list", client.list_resources),
        ("resources/templates/list", client.list_resource_templates),
    )
    for method, operation in surface_calls:
        try:
            result = await operation()
        except MCPError as error:
            if error.code != METHOD_NOT_FOUND:
                raise
            outcome = (
                "expected-rejection"
                if mode != "legacy"
                else "upstream-rejection"
            )
            print_json(
                {
                    "phase": method,
                    "outcome": outcome,
                    "errorCode": error.code,
                }
            )
            continue

        if mode != "legacy":
            raise RuntimeError(
                f"Modern tool-only proxy unexpectedly accepted {method}."
            )
        item_count = 0
        for attribute in ("prompts", "resources", "resource_templates"):
            items = getattr(result, attribute, None)
            if isinstance(items, list):
                item_count = len(items)
                break
        print_json(
            {
                "phase": method,
                "outcome": "success",
                "itemCount": item_count,
            }
        )


async def _run_parallel_list_smoke(
    client: Client,
    *,
    count: int,
    require_complete: bool,
) -> None:
    results: dict[int, types.ListToolsResult] = {}

    async def list_tools(index: int) -> None:
        result = await client.list_tools()
        if require_complete and result.result_type != "complete":
            raise RuntimeError(
                "Parallel modern tools/list returned "
                f"resultType={result.result_type!r}"
            )
        results[index] = result

    async with anyio.create_task_group() as task_group:
        for index in range(count):
            task_group.start_soon(list_tools, index)

    ordered_results = [results[index] for index in range(count)]
    print_json(
        {
            "phase": "tools/list-parallel",
            "requestCount": count,
            "resultTypes": [
                result.result_type for result in ordered_results
            ],
            "toolCounts": [
                len(result.tools) for result in ordered_results
            ],
        }
    )


def build_runscript_arguments() -> dict[str, str]:
    """Return only fields accepted by CloudSpec's strict RunScript schema."""
    return {
        "script": RUNSCRIPT_SOURCE,
    }


async def _run_runscript_smoke(
    client: Client,
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_result = await client.call_tool(
        RUNSCRIPT_TOOL,
        build_runscript_arguments(),
    )
    if run_result.is_error:
        raise RuntimeError("AlibabaCloud___RunScript returned isError=true.")

    start_task = extract_result_payload(run_result)
    process_id = extract_process_id(start_task)
    print_json(
        {
            "phase": "runscript",
            "processID": process_id,
            "status": start_task.get("status"),
            "nextAction": start_task.get("nextAction"),
            "waitTimedOut": start_task.get("waitTimedOut"),
        }
    )

    deadline = anyio.current_time() + args.timeout_seconds
    while True:
        get_task_result = await client.call_tool(
            GET_TASK_TOOL,
            {
                "processID": process_id,
                "waitTimeoutSeconds": 20,
                "pollIntervalSeconds": 2,
            },
        )
        if get_task_result.is_error:
            raise RuntimeError("AlibabaCloud___GetTask returned isError=true.")
        task = extract_result_payload(get_task_result)
        status = task.get("status")
        print_json(
            {
                "phase": "get-task",
                "processID": process_id,
                "status": status,
                "nextAction": task.get("nextAction"),
                "waitTimedOut": task.get("waitTimedOut"),
            }
        )

        if status in TERMINAL_STATUSES:
            validate_successful_task(task)
            print_json(summarize_completed_task(task))
            return task
        if status not in NON_TERMINAL_STATUSES:
            raise RuntimeError(
                f"Unknown GetTask status for processID={process_id}: {status}"
            )
        if anyio.current_time() >= deadline:
            raise TimeoutError(
                f"GetTask did not reach terminal state for processID={process_id}"
            )
        await anyio.sleep(args.poll_interval_seconds)


async def run_e2e(args: argparse.Namespace) -> None:
    parameters = build_server_parameters(args)
    transport = stdio_client(parameters)
    async with Client(
        transport,
        mode=args.mode,
        cache=None,
    ) as client:
        if (
            args.mode in ("auto", "2026-07-28")
            and client.protocol_version != "2026-07-28"
        ):
            raise RuntimeError(
                "Modern connection did not select MCP 2026-07-28: "
                f"{client.protocol_version}"
            )

        capabilities = client.server_capabilities
        print_json(
            {
                "phase": "connected",
                "requestedMode": args.mode,
                "protocolVersion": client.protocol_version,
                "capabilities": capabilities.model_dump(
                    by_alias=True,
                    exclude_none=True,
                ),
            }
        )

        tool_names: list[str] = []
        listed_tools: list[types.Tool] = []
        for iteration in range(1, args.list_repeat_count + 1):
            tools_result = await client.list_tools()
            listed_tools = tools_result.tools
            tool_names = [tool.name for tool in listed_tools]
            print_json(
                {
                    "phase": "tools/list",
                    "iteration": iteration,
                    "resultType": tools_result.result_type,
                    "toolCount": len(tool_names),
                    "requiredToolsPresent": {
                        RUNSCRIPT_TOOL: RUNSCRIPT_TOOL in tool_names,
                        GET_TASK_TOOL: GET_TASK_TOOL in tool_names,
                    },
                }
            )
            if (
                args.mode in ("auto", "2026-07-28")
                and tools_result.result_type != "complete"
            ):
                raise RuntimeError(
                    "Modern tools/list returned "
                    f"resultType={tools_result.result_type!r}"
                )

        if args.print_tool_contracts:
            print_json(
                {
                    "phase": "tool-contracts",
                    "toolCount": len(listed_tools),
                    "tools": [
                        summarize_tool_contract(tool)
                        for tool in listed_tools
                    ],
                }
            )

        if args.parallel_list_count:
            await _run_parallel_list_smoke(
                client,
                count=args.parallel_list_count,
                require_complete=args.mode in ("auto", "2026-07-28"),
            )

        if args.run_protocol_behavior_smoke:
            await _run_protocol_behavior_smoke(client, mode=args.mode)

        if args.run_all_tools_smoke:
            validate_expected_tool_surface(tool_names)
            await _run_all_tools_smoke(client, args)

        if args.run_readonly_tool_smoke:
            missing_readonly_tools = {
                tool_name
                for tool_name, _ in READONLY_TOOL_CASES
                if tool_name not in tool_names
            }
            if missing_readonly_tools:
                raise RuntimeError(
                    "Required read-only tools are missing: "
                    f"{sorted(missing_readonly_tools)}"
                )
            await _run_readonly_tool_smoke(client)

        if args.run_runscript_smoke:
            missing = {
                RUNSCRIPT_TOOL,
                GET_TASK_TOOL,
            }.difference(tool_names)
            if missing:
                raise RuntimeError(
                    f"Required RunScript tools are missing: {sorted(missing)}"
                )
            await _run_runscript_smoke(client, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the current local Proxy source and test it against a "
            "remote CloudSpec MCP endpoint."
        )
    )
    parser.add_argument("--server-url", required=True)
    parser.add_argument(
        "--mode",
        choices=("auto", "2026-07-28", "legacy"),
        required=True,
    )
    parser.add_argument("--log-file", required=True)
    parser.add_argument(
        "--list-repeat-count",
        type=int,
        default=1,
        choices=range(1, 11),
        metavar="1..10",
    )
    parser.add_argument(
        "--parallel-list-count",
        type=int,
        default=0,
        choices=range(0, 21),
        metavar="0..20",
    )
    parser.add_argument(
        "--proxy-read-timeout-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=600.0,
    )
    parser.add_argument(
        "--bearer-token-env",
        help=(
            "Optional environment variable containing a bearer token. The "
            "value is forwarded to the child only through "
            "ALIBABACLOUD_MCP_BEARER_TOKEN."
        ),
    )
    parser.add_argument(
        "--run-readonly-tool-smoke",
        action="store_true",
    )
    parser.add_argument(
        "--print-tool-contracts",
        action="store_true",
    )
    parser.add_argument(
        "--run-all-tools-smoke",
        action="store_true",
    )
    parser.add_argument(
        "--run-protocol-behavior-smoke",
        action="store_true",
    )
    parser.add_argument(
        "--run-runscript-smoke",
        action="store_true",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        anyio.run(run_e2e, args)
    except Exception as exc:
        message = _redact_error_message(_actionable_error_message(exc))
        print(f"Error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
