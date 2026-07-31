from __future__ import annotations

from typing import Final, Literal

from mcp_types.version import MODERN_PROTOCOL_VERSIONS

ProtocolMode = Literal["2026-07-28", "legacy"]

MODERN_PROTOCOL_MODE: Final[ProtocolMode] = "2026-07-28"
LEGACY_PROTOCOL_MODE: Final[ProtocolMode] = "legacy"


class NonRetryableProxyError(RuntimeError):
    """Base class for permanent protocol and feature errors."""


class ProtocolModeMismatchError(NonRetryableProxyError):
    """Raised when one downstream connection attempts to mix protocol eras."""


class UnsupportedProtocolTransportError(NonRetryableProxyError):
    """Raised when a protocol era cannot use the selected transport."""


class UnsupportedProtocolFeatureError(NonRetryableProxyError):
    """Raised when the upstream requests a feature outside proxy scope."""


def to_upstream_protocol_mode(protocol_version: str) -> ProtocolMode:
    if protocol_version in MODERN_PROTOCOL_VERSIONS:
        return MODERN_PROTOCOL_MODE
    return LEGACY_PROTOCOL_MODE
