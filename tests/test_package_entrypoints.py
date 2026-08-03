import re
from pathlib import Path

from alibabacloud.mcp_proxy import __version__


ENTRYPOINT_TARGET = "alibabacloud.mcp_proxy.cli:main"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_proxy_console_scripts_include_windows_uv_084_compatibility_alias() -> None:
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    public_script = f'"alibabacloud.mcp-proxy" = "{ENTRYPOINT_TARGET}"'
    compatibility_script = f'"alibabacloud" = "{ENTRYPOINT_TARGET}"'

    assert public_script in pyproject
    assert compatibility_script in pyproject


def test_runtime_version_matches_project_version() -> None:
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert match is not None
    assert __version__ == match.group(1)
