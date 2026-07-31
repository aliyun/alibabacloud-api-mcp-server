from importlib.metadata import version

from alibabacloud.mcp_proxy import __version__


def test_runtime_version_matches_package_metadata() -> None:
    assert __version__ == version("alibabacloud.mcp-proxy")
