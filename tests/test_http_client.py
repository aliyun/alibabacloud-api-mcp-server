from __future__ import annotations

from unittest.mock import patch

import pytest

from alibabacloud.mcp_proxy.transport.http_client import (
    ProxyDependencyError,
    create_async_client,
)


def test_missing_socks_dependency_has_actionable_error() -> None:
    with patch(
        "alibabacloud.mcp_proxy.transport.http_client.httpx.AsyncClient",
        side_effect=ImportError("Using SOCKS proxy, but the 'socksio' package is not installed"),
    ):
        with pytest.raises(ProxyDependencyError) as error:
            create_async_client()

    message = str(error.value)
    assert "SOCKS proxy is configured" in message
    assert "httpx[socks]" in message
    assert "NO_PROXY" in message


def test_unrelated_import_error_is_not_rewritten() -> None:
    with patch(
        "alibabacloud.mcp_proxy.transport.http_client.httpx.AsyncClient",
        side_effect=ImportError("unrelated optional package"),
    ):
        with pytest.raises(ImportError, match="unrelated optional package"):
            create_async_client()
