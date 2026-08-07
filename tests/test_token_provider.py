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
    assert mock_ims.await_args.kwargs["policy"] is None


@pytest.mark.asyncio
@patch(
    "alibabacloud.mcp_proxy.auth.ims_access_token.generate_access_token_async",
    new_callable=AsyncMock,
)
async def test_build_token_provider_forwards_boundary_policy(mock_ims: AsyncMock) -> None:
    policy = (
        '{"Version":"1","Statement":[{"Effect":"Deny",'
        '"NotAction":"ram:UpdateAccessKey","Resource":"*"}]}'
    )
    mock_ims.return_value = BearerToken(value="ims-token")
    provider = build_token_provider(
        TokenSettings(
            bearer_token=None,
            token_command=None,
            ims_client_id=DEFAULT_IMS_CLIENT_ID,
            ims_scope=DEFAULT_IMS_SCOPE,
            ims_endpoint=DEFAULT_IMS_ENDPOINT,
            boundary_policy=policy,
        )
    )
    assert await provider.get_token() == "ims-token"
    assert mock_ims.await_args.kwargs["policy"] == policy


@pytest.mark.asyncio
async def test_provider_refetches_when_generation_advances() -> None:
    source = FakeTokenSource(
        [
            BearerToken(value="tok-a", expires_at=datetime.now(UTC) + timedelta(minutes=5)),
            BearerToken(value="tok-b", expires_at=datetime.now(UTC) + timedelta(minutes=5)),
        ]
    )
    gen = {"v": 1}
    provider = CachedBearerTokenProvider(
        source, refresh_skew_seconds=30, generation_provider=lambda: gen["v"]
    )

    assert await provider.get_token() == "tok-a"
    assert await provider.get_token() == "tok-a"  # cached, gen unchanged
    gen["v"] = 2
    assert await provider.get_token() == "tok-b"  # gen advanced -> refetch
    assert source.calls == 2


@pytest.mark.asyncio
async def test_provider_without_generation_provider_caches_as_before() -> None:
    source = FakeTokenSource(
        [BearerToken(value="only", expires_at=datetime.now(UTC) + timedelta(minutes=5))]
    )
    provider = CachedBearerTokenProvider(source, refresh_skew_seconds=30)
    assert await provider.get_token() == "only"
    assert await provider.get_token() == "only"
    assert source.calls == 1
