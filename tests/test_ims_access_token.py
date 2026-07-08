from __future__ import annotations

from datetime import UTC, datetime
import logging

import pytest

from alibabacloud.mcp_proxy.auth.ims_access_token import (
    _log_ims_generate_access_token_response,
    extract_token_from_ims_api_response,
    parse_ims_generate_access_token_body,
)
from alibabacloud.mcp_proxy.auth.token_provider import TokenAcquisitionError


def test_parse_ims_body_extracts_access_token_pascal_case() -> None:
    token, expires = parse_ims_generate_access_token_body(
        {"AccessToken": "abc", "ExpiresIn": 3600}
    )
    assert token == "abc"
    assert expires is not None


def test_parse_ims_body_extracts_access_token_snake_case() -> None:
    token, _ = parse_ims_generate_access_token_body({"access_token": "xyz"})
    assert token == "xyz"


def test_parse_ims_body_missing_token_raises() -> None:
    with pytest.raises(TokenAcquisitionError):
        parse_ims_generate_access_token_body({})


def test_parse_ims_body_expire_time_iso() -> None:
    token, expires = parse_ims_generate_access_token_body(
        {"AccessToken": "t", "ExpireTime": "2030-01-01T00:00:00Z"}
    )
    assert token == "t"
    assert expires is not None
    assert expires.tzinfo == UTC


def test_parse_ims_body_json_string() -> None:
    token, _ = parse_ims_generate_access_token_body('{"AccessToken":"from-json"}')
    assert token == "from-json"


def test_parse_ims_body_nested_data_object() -> None:
    """IMS wraps token under Data (GenerateAccessToken success shape)."""
    payload = {
        "RequestId": "4E1D70EE-9F90-15F2-95C5-69AC01042C54",
        "Data": {
            "TokenType": "Bearer",
            "ExpiresIn": "259199",
            "Scope": "/internal/acs/openapi",
            "AccessToken": "jwt-token-value",
        },
    }
    token, expires = parse_ims_generate_access_token_body(payload)
    assert token == "jwt-token-value"
    assert expires is not None


def test_parse_ims_body_rpc_error_message() -> None:
    with pytest.raises(TokenAcquisitionError, match="IMS GenerateAccessToken failed"):
        parse_ims_generate_access_token_body(
            {"Code": "InvalidParameter", "Message": "bad scope", "RequestId": "x"}
        )


def test_extract_token_from_tea_openapi_response_shape() -> None:
    """tea ``call_api_async`` wraps RPC JSON under ``body``."""
    resp = {
        "body": {
            "RequestId": "4E1D70EE-9F90-15F2-95C5-69AC01042C54",
            "Data": {
                "TokenType": "Bearer",
                "ExpiresIn": "259199",
                "AccessToken": "eyJhbGciOiJ.unit-test",
            },
        },
        "headers": {},
        "statusCode": 200,
    }
    token, expires = extract_token_from_ims_api_response(resp)
    assert token == "eyJhbGciOiJ.unit-test"
    assert expires is not None


def test_ims_response_logging_redacts_tokens_at_debug(caplog) -> None:
    caplog.set_level("DEBUG", logger="alibabacloud.mcp_proxy.auth.ims_access_token")
    response = {
        "body": {
            "Data": {
                "AccessToken": "secret-access-token",
                "SecurityToken": "secret-security-token",
                "RefreshToken": "secret-refresh-token",
            }
        },
        "statusCode": 200,
    }

    _log_ims_generate_access_token_response(response)

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret-access-token" not in logs
    assert "secret-security-token" not in logs
    assert "secret-refresh-token" not in logs
    assert "***REDACTED***" in logs
