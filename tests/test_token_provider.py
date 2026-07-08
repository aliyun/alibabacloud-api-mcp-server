from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from alibabacloud.mcp_proxy.auth.ims_access_token import (
    DEFAULT_IMS_CLIENT_ID,
    DEFAULT_IMS_ENDPOINT,
    DEFAULT_IMS_SCOPE,
)
from alibabacloud.mcp_proxy.auth.token_provider import (
    BearerToken,
    CachedBearerTokenProvider,
    StaticBearerTokenSource,
    TokenAcquisitionError,
    build_token_provider,
)
from alibabacloud.mcp_proxy.config import TokenSettings


class FakeTokenSource:
    def __init__(self, tokens: list[BearerToken]) -> None:
        self.tokens = tokens
        self.calls = 0

    async def fetch_token(self) -> BearerToken:
        token = self.tokens[min(self.calls, len(self.tokens) - 1)]
        self.calls += 1
        return token


@pytest.mark.asyncio
async def test_static_token_provider_returns_configured_token() -> None:
    provider = build_token_provider(
        TokenSettings(
            bearer_token="abc123",
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
        )
    )

    token = await provider.get_token()

    assert token == "abc123"


@pytest.mark.asyncio
async def test_cached_token_provider_refreshes_expiring_tokens() -> None:
    source = FakeTokenSource(
        [
            BearerToken(
                value="old-token",
                expires_at=datetime.now(UTC) + timedelta(seconds=10),
            ),
            BearerToken(
                value="new-token",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
        ]
    )
    provider = CachedBearerTokenProvider(source, refresh_skew_seconds=30)

    first = await provider.get_token()
    second = await provider.get_token()

    assert first == "old-token"
    assert second == "new-token"
    assert source.calls == 2


@pytest.mark.asyncio
@patch(
    "alibabacloud.mcp_proxy.auth.ims_access_token.generate_access_token_async",
    new_callable=AsyncMock,
)
async def test_build_token_provider_uses_ims_when_no_explicit_token(mock_ims: AsyncMock) -> None:
    mock_ims.return_value = BearerToken(value="ims-token")
    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
        )
    )
    assert await provider.get_token() == "ims-token"
    mock_ims.assert_awaited()


def test_build_token_provider_uses_explicit_static_ak_env(monkeypatch) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-ak-secret")
    monkeypatch.delenv("ALIBABA_CLOUD_SECURITY_TOKEN", raising=False)

    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
        )
    )

    source = provider._source
    assert source._credential_client is not None
    credential = source._credential_client.get_credential()
    assert credential.provider_name == "static_ak"
    assert credential.access_key_id == "test-ak-id"
    assert credential.security_token is None


def test_build_token_provider_uses_explicit_static_sts_env(monkeypatch) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-ak-secret")
    monkeypatch.setenv("ALIBABA_CLOUD_SECURITY_TOKEN", "test-security-token")

    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
        )
    )

    source = provider._source
    assert source._credential_client is not None
    credential = source._credential_client.get_credential()
    assert credential.provider_name == "static_sts"
    assert credential.access_key_id == "test-ak-id"
    assert credential.security_token == "test-security-token"


def test_build_token_provider_rejects_partial_static_ak_env_missing_secret(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak-id")
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_SECURITY_TOKEN", raising=False)

    with pytest.raises(TokenAcquisitionError, match="ALIBABA_CLOUD_ACCESS_KEY_SECRET"):
        build_token_provider(
            TokenSettings(
                bearer_token=None,
                token_command=None,
                ims_client_id=DEFAULT_IMS_CLIENT_ID,
                ims_scope=DEFAULT_IMS_SCOPE,
                ims_endpoint=DEFAULT_IMS_ENDPOINT,
            )
        )


def test_build_token_provider_rejects_partial_static_ak_env_missing_id(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-ak-secret")
    monkeypatch.delenv("ALIBABA_CLOUD_SECURITY_TOKEN", raising=False)

    with pytest.raises(TokenAcquisitionError, match="ALIBABA_CLOUD_ACCESS_KEY_ID"):
        build_token_provider(
            TokenSettings(
                bearer_token=None,
                token_command=None,
                ims_client_id=DEFAULT_IMS_CLIENT_ID,
                ims_scope=DEFAULT_IMS_SCOPE,
                ims_endpoint=DEFAULT_IMS_ENDPOINT,
            )
        )


def test_build_token_provider_preserves_default_chain_without_static_ak_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_SECURITY_TOKEN", raising=False)

    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
        )
    )

    source = provider._source
    assert source._credential_client is None


@pytest.mark.asyncio
@patch(
    "alibabacloud.mcp_proxy.auth.ims_access_token.generate_access_token_async",
    new_callable=AsyncMock,
)
async def test_static_ak_refresh_reuses_explicit_credential_client(
    mock_ims: AsyncMock,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-ak-secret")
    monkeypatch.delenv("ALIBABA_CLOUD_SECURITY_TOKEN", raising=False)
    mock_ims.side_effect = [
        BearerToken(
            value="old-token",
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        ),
        BearerToken(
            value="new-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    ]

    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
            refresh_skew_seconds=30,
        )
    )

    assert await provider.get_token() == "old-token"
    assert await provider.get_token() == "new-token"

    first_client = mock_ims.await_args_list[0].kwargs["credential_client"]
    second_client = mock_ims.await_args_list[1].kwargs["credential_client"]
    assert first_client is not None
    assert first_client is second_client
