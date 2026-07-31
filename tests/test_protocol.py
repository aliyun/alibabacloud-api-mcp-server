from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

from alibabacloud.mcp_proxy.protocol import (
    LEGACY_PROTOCOL_MODE,
    MODERN_PROTOCOL_MODE,
    to_upstream_protocol_mode,
)


def test_all_modern_versions_map_to_modern_mode() -> None:
    assert MODERN_PROTOCOL_VERSIONS
    assert {
        to_upstream_protocol_mode(version) for version in MODERN_PROTOCOL_VERSIONS
    } == {MODERN_PROTOCOL_MODE}


def test_all_handshake_versions_map_to_legacy_mode() -> None:
    assert HANDSHAKE_PROTOCOL_VERSIONS
    assert {
        to_upstream_protocol_mode(version) for version in HANDSHAKE_PROTOCOL_VERSIONS
    } == {LEGACY_PROTOCOL_MODE}


def test_unknown_non_modern_version_maps_to_legacy_mode() -> None:
    assert to_upstream_protocol_mode("2025-01-01") == LEGACY_PROTOCOL_MODE
