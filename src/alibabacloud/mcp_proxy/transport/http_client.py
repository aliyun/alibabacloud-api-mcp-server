"""Shared HTTP client construction and proxy dependency diagnostics."""

from __future__ import annotations

from typing import Any

import httpx


class ProxyDependencyError(RuntimeError):
    """Raised when an environment-configured proxy needs an optional dependency."""


def create_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Create an HTTPX client and turn missing SOCKS support into a useful error."""
    try:
        return httpx.AsyncClient(**kwargs)
    except ImportError as exc:
        message = str(exc)
        if "socks" not in message.lower():
            raise
        raise ProxyDependencyError(
            "A SOCKS proxy is configured through HTTP_PROXY, HTTPS_PROXY, or "
            "ALL_PROXY, but SOCKS support is unavailable. Reinstall "
            "alibabacloud.mcp-proxy 0.2.13 or later, or install "
            "'httpx[socks]'; alternatively, set NO_PROXY for the Alibaba Cloud "
            "endpoint."
        ) from exc
