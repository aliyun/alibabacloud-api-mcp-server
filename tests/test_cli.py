from __future__ import annotations

from unittest.mock import patch

import pytest

from alibabacloud.mcp_proxy.cli import build_parser, main, parse_config
from alibabacloud.mcp_proxy.config import (
    BOUNDARY_POLICY_MAX_LENGTH,
    ProxyConfigurationError,
    SiteType,
)
from alibabacloud.mcp_proxy.auth.token_provider import TokenAcquisitionError


def test_parse_config_uses_builtin_defaults_when_no_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ALIBABACLOUD_MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("ALIBABACLOUD_MCP_SITE_TYPE", raising=False)

    config = parse_config([])

    assert config.server_url is None
    assert config.site_type is SiteType.CN
    assert config.debug is False
    assert config.log_file is None


def test_parse_config_uses_cli_values() -> None:
    config = parse_config(
        [
            "--server-url",
            "https://example.com/mcp",
            "--retry-max-attempts",
            "5",
        ]
    )

    assert config.server_url == "https://example.com/mcp"
    assert config.retry.max_attempts == 5


def test_parse_config_allow_tools_supports_commas_and_repeated_flags() -> None:
    config = parse_config(
        [
            "--allow-tools",
            "AlibabaCloud___RunScript,AlibabaCloud___GetTask",
            "--allow-tools",
            "AlibabaCloud___RunScript",
        ]
    )

    assert config.token.allowed_tools == (
        "AlibabaCloud___RunScript",
        "AlibabaCloud___GetTask",
    )


def test_parse_config_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("ALIBABACLOUD_MCP_SERVER_URL", "https://env.example/mcp")

    config = parse_config([])

    assert config.server_url == "https://env.example/mcp"


def test_parse_config_site_type_intl() -> None:
    config = parse_config(["--site-type", "INTL"])

    assert config.site_type is SiteType.INTL
    assert config.token.ims_client_id == "4195410055503316452"


def test_parse_config_site_type_cn_default_client_id() -> None:
    config = parse_config(["--site-type", "CN"])

    assert config.site_type is SiteType.CN
    assert config.token.ims_client_id == "4071151845732613353"


def test_parse_config_ims_client_and_scope_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ALIBABACLOUD_MCP_SERVER_URL", "https://env.example/mcp")
    monkeypatch.setenv("ALIBABACLOUD_MCP_CLIENT_ID", "999")
    monkeypatch.setenv("ALIBABACLOUD_MCP_SCOPE", "/custom/scope")

    config = parse_config([])

    assert config.token.ims_client_id == "999"
    assert config.token.ims_scope == "/custom/scope"


def test_parse_config_cli_overrides_ims_defaults() -> None:
    config = parse_config(
        [
            "--server-url",
            "https://example.com/mcp",
            "--client-id",
            "111",
            "--scope",
            "/cli-scope",
            "--ims-endpoint",
            "ims.cn-hangzhou.aliyuncs.com",
        ]
    )

    assert config.token.ims_client_id == "111"
    assert config.token.ims_scope == "/cli-scope"
    assert config.token.ims_endpoint == "ims.cn-hangzhou.aliyuncs.com"


_SAMPLE_BOUNDARY_POLICY = (
    '{"Version":"1","Statement":[{"Effect":"Deny",'
    '"NotAction":"ram:UpdateAccessKey","Resource":"*"}]}'
)
_BOUNDARY_POLICY_PREFIX = (
    '{"Version":"1","Statement":[{"Effect":"Deny",'
    '"Action":"ecs:DescribeInstances","Resource":"'
)
_BOUNDARY_POLICY_SUFFIX = '"}]}'


def test_parse_config_boundary_policy_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("ALIBABACLOUD_MCP_BOUNDARY_POLICY", raising=False)

    config = parse_config([])

    assert config.token.boundary_policy is None


def test_parse_config_boundary_policy_from_cli() -> None:
    config = parse_config(["--boundary-policy", _SAMPLE_BOUNDARY_POLICY])

    assert config.token.boundary_policy == _SAMPLE_BOUNDARY_POLICY


def test_parse_config_boundary_policy_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ALIBABACLOUD_MCP_BOUNDARY_POLICY", _SAMPLE_BOUNDARY_POLICY)

    config = parse_config([])

    assert config.token.boundary_policy == _SAMPLE_BOUNDARY_POLICY


def test_parse_config_boundary_policy_rejects_over_max_length(monkeypatch) -> None:
    monkeypatch.delenv("ALIBABACLOUD_MCP_BOUNDARY_POLICY", raising=False)

    with pytest.raises(ProxyConfigurationError, match="512 characters"):
        parse_config(["--boundary-policy", "x" * (BOUNDARY_POLICY_MAX_LENGTH + 1)])


def test_parse_config_boundary_policy_accepts_max_length(monkeypatch) -> None:
    monkeypatch.delenv("ALIBABACLOUD_MCP_BOUNDARY_POLICY", raising=False)
    resource = "*" * (
        BOUNDARY_POLICY_MAX_LENGTH
        - len(_BOUNDARY_POLICY_PREFIX)
        - len(_BOUNDARY_POLICY_SUFFIX)
    )
    policy = f"{_BOUNDARY_POLICY_PREFIX}{resource}{_BOUNDARY_POLICY_SUFFIX}"

    config = parse_config(["--boundary-policy", policy])

    assert len(policy) == BOUNDARY_POLICY_MAX_LENGTH
    assert config.token.boundary_policy == policy


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ("not-json", "valid JSON"),
        ('["not", "an", "object"]', "JSON object"),
        ('{"Version":"2","Statement":[]}', "Version must be '1'"),
        ('{"Version":"1","Statement":[]}', "Statement must be a non-empty list"),
        ('{"Version":"1","Statement":["bad"]}', "statement 1 must be an object"),
        (
            '{"Version":"1","Statement":[{"Effect":"Allow","Action":"ecs:*","Resource":"*"}]}',
            "Effect 'Deny'",
        ),
        (
            '{"Version":"1","Statement":[{"Effect":"Deny","Resource":"*"}]}',
            "exactly one of 'Action' or 'NotAction'",
        ),
        (
            '{"Version":"1","Statement":[{"Effect":"Deny","Action":"ecs:*",'
            '"NotAction":"ram:*","Resource":"*"}]}',
            "exactly one of 'Action' or 'NotAction'",
        ),
        (
            '{"Version":"1","Statement":[{"Effect":"Deny","Action":[],"Resource":"*"}]}',
            "field 'Action'",
        ),
        (
            '{"Version":"1","Statement":[{"Effect":"Deny","Action":"ecs:*","Resource":[]}]}',
            "field 'Resource'",
        ),
    ],
)
def test_parse_config_boundary_policy_rejects_invalid_shape(
    monkeypatch,
    policy: str,
    message: str,
) -> None:
    monkeypatch.delenv("ALIBABACLOUD_MCP_BOUNDARY_POLICY", raising=False)

    with pytest.raises(ProxyConfigurationError, match=message):
        parse_config(["--boundary-policy", policy])


def test_parse_config_boundary_policy_accepts_string_lists() -> None:
    policy = (
        '{"Version":"1","Statement":[{"Effect":"Deny",'
        '"Action":["ecs:DeleteInstance","ecs:RunCommand"],'
        '"Resource":["*"]}]}'
    )

    config = parse_config(["--boundary-policy", policy])

    assert config.token.boundary_policy == policy


def test_boundary_policy_help_uses_configured_max_length() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert f"max {BOUNDARY_POLICY_MAX_LENGTH} characters" in help_text


def test_parse_config_debug_flag() -> None:
    config = parse_config(["--debug", "--log-file", "/tmp/test.log"])

    assert config.debug is True
    assert config.log_file == "/tmp/test.log"


def test_main_debug_without_log_file_exits() -> None:
    with pytest.raises(SystemExit):
        main(["--debug"])


def test_main_runtime_token_error_with_debug(tmp_path) -> None:
    log_path = tmp_path / "proxy.log"

    with (
        patch("alibabacloud.mcp_proxy.cli.anyio.run", side_effect=TokenAcquisitionError("boom")),
        pytest.raises(SystemExit, match="boom"),
    ):
        main(["--debug", "--log-file", str(log_path)])

    assert log_path.exists()
    assert "Proxy terminated with configuration/token error: boom" in log_path.read_text()


def test_main_runtime_token_error_without_debug() -> None:
    with (
        patch("alibabacloud.mcp_proxy.cli.anyio.run", side_effect=TokenAcquisitionError("boom")),
        pytest.raises(SystemExit, match="boom"),
    ):
        main([])


def test_telemetry_view_subcommand_default_port() -> None:
    parser = build_parser()
    args = parser.parse_args(["telemetry-view"])
    assert args.command == "telemetry-view"
    assert args.tv_port == 18321
    assert args.tv_no_open is False


def test_telemetry_view_subcommand_custom_port() -> None:
    parser = build_parser()
    args = parser.parse_args(["telemetry-view", "--port", "9999"])
    assert args.tv_port == 9999


def test_telemetry_view_subcommand_no_open() -> None:
    parser = build_parser()
    args = parser.parse_args(["telemetry-view", "--no-open"])
    assert args.tv_no_open is True
