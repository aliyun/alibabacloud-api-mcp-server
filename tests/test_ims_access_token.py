from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alibabacloud.mcp_proxy.auth.ims_access_token import (
    extract_token_from_ims_api_response,
    generate_access_token_async,
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


_IMS_OK_RESPONSE = {
    "body": {"Data": {"AccessToken": "jwt", "ExpiresIn": "3600"}},
    "headers": {},
    "statusCode": 200,
}


@pytest.mark.asyncio
async def test_generate_access_token_includes_policy_query_when_set() -> None:
    fake_client = MagicMock()
    fake_client.call_api_async = AsyncMock(return_value=_IMS_OK_RESPONSE)
    policy = (
        '{"Version":"1","Statement":[{"Effect":"Deny",'
        '"NotAction":"ram:UpdateAccessKey","Resource":"*"}]}'
    )

    with patch(
        "alibabacloud.mcp_proxy.auth.ims_access_token.OpenApiClient",
        return_value=fake_client,
    ):
        token = await generate_access_token_async(
            client_id="cid",
            scope="/scope",
            policy=policy,
            credential_client=MagicMock(),
        )

    assert token.value == "jwt"
    request = fake_client.call_api_async.await_args.args[1]
    assert request.query.get("Policy") == policy


@pytest.mark.asyncio
async def test_generate_access_token_omits_policy_query_when_absent() -> None:
    fake_client = MagicMock()
    fake_client.call_api_async = AsyncMock(return_value=_IMS_OK_RESPONSE)

    with patch(
        "alibabacloud.mcp_proxy.auth.ims_access_token.OpenApiClient",
        return_value=fake_client,
    ):
        await generate_access_token_async(
            client_id="cid",
            scope="/scope",
            credential_client=MagicMock(),
        )

    request = fake_client.call_api_async.await_args.args[1]
    assert "Policy" not in request.query


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


@pytest.mark.asyncio
async def test_ims_source_uses_tracker_client(monkeypatch) -> None:
    from alibabacloud.mcp_proxy.auth import ims_access_token as mod
    from alibabacloud.mcp_proxy.auth.ims_access_token import ImsBearerTokenSource

    sentinel_client = object()

    class FakeTracker:
        def get_client(self):
            return sentinel_client

    captured = {}

    async def fake_generate(*, client_id, scope, endpoint, policy, credential_client):
        captured["client"] = credential_client
        from alibabacloud.mcp_proxy.auth.token_provider import BearerToken

        return BearerToken(value="tok")

    monkeypatch.setattr(mod, "generate_access_token_async", fake_generate)

    source = ImsBearerTokenSource(
        client_id="cid", scope="scope", credential_tracker=FakeTracker()
    )
    token = await source.fetch_token()

    assert token.value == "tok"
    assert captured["client"] is sentinel_client
