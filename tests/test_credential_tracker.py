from __future__ import annotations

import os

import pytest

from alibabacloud.mcp_proxy.auth import credential_tracker as ct
from alibabacloud.mcp_proxy.auth.credential_tracker import (
    CredentialRefreshError,
    CredentialTracker,
)


class FakeCredModel:
    def __init__(self, ak_id: str) -> None:
        self._ak_id = ak_id

    def get_access_key_id(self) -> str:
        return self._ak_id


class FakeClient:
    def __init__(self, ak_id: str) -> None:
        self._ak_id = ak_id

    def get_credential(self) -> FakeCredModel:
        return FakeCredModel(self._ak_id)


def _factory(ak_ids: list[str]):
    """Return a client_factory yielding clients with successive AK ids."""
    state = {"i": 0}

    def make():
        ak = ak_ids[min(state["i"], len(ak_ids) - 1)]
        state["i"] += 1
        return FakeClient(ak)

    return make


def _write(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write(text)


@pytest.mark.asyncio
async def test_no_file_change_keeps_generation_and_client(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')
    tracker = CredentialTracker(profile_file=str(cfg), client_factory=_factory(["ak-1"]))

    gen0 = tracker.current_generation()
    client0 = tracker.get_client()

    assert await tracker.refresh_if_stale() == gen0
    assert tracker.get_client() is client0  # no rebuild


@pytest.mark.asyncio
async def test_identity_switch_bumps_generation(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')
    tracker = CredentialTracker(
        profile_file=str(cfg), client_factory=_factory(["ak-1", "ak-2"])
    )
    gen0 = tracker.current_generation()

    # Change file content AND mtime, next resolve yields a different AK id.
    os.utime(str(cfg), (gen0 + 1000, gen0 + 1000))
    _write(str(cfg), '{"current":"b"}')

    gen1 = await tracker.refresh_if_stale()
    assert gen1 == gen0 + 1
    assert tracker.get_client()._ak_id == "ak-2"


@pytest.mark.asyncio
async def test_file_touched_but_same_identity_keeps_generation(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')
    tracker = CredentialTracker(
        profile_file=str(cfg), client_factory=_factory(["ak-1", "ak-1"])
    )
    gen0 = tracker.current_generation()

    os.utime(str(cfg), (gen0 + 1000, gen0 + 1000))
    assert await tracker.refresh_if_stale() == gen0  # same AK -> no bump


@pytest.mark.asyncio
async def test_missing_file_is_noop(tmp_path) -> None:
    cfg = tmp_path / "config.json"  # never created
    tracker = CredentialTracker(profile_file=str(cfg), client_factory=_factory(["ak-1"]))
    gen0 = tracker.current_generation()
    assert await tracker.refresh_if_stale() == gen0


@pytest.mark.asyncio
async def test_resolve_failure_rejects_old_identity(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')

    class BoomClient:
        def get_credential(self):
            raise RuntimeError("resolve failed")

    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeClient("ak-1")  # initial seed succeeds
        return BoomClient()

    tracker = CredentialTracker(profile_file=str(cfg), client_factory=factory)
    gen0 = tracker.current_generation()

    os.utime(str(cfg), (gen0 + 1000, gen0 + 1000))
    _write(str(cfg), '{"current":"b"}')
    with pytest.raises(CredentialRefreshError, match="refusing to reuse"):
        await tracker.refresh_if_stale()
    assert tracker.current_generation() == gen0  # no bump on failure
    assert tracker.get_client()._ak_id == "ak-1"  # kept old working client


@pytest.mark.asyncio
async def test_transient_failure_retries_on_next_request(tmp_path) -> None:
    """A failed resolve must not consume the file change; a later resolve retries."""
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')

    class BoomClient:
        def get_credential(self):
            raise RuntimeError("transient resolve failure")

    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeClient("ak-1")  # initial seed succeeds
        if calls["n"] == 2:
            return BoomClient()  # first refresh fails transiently
        return FakeClient("ak-2")  # retry now succeeds

    tracker = CredentialTracker(profile_file=str(cfg), client_factory=factory)
    gen0 = tracker.current_generation()

    os.utime(str(cfg), (gen0 + 1000, gen0 + 1000))
    _write(str(cfg), '{"current":"b"}')

    # First refresh: resolution fails, so the file signature is NOT advanced.
    with pytest.raises(CredentialRefreshError, match="refusing to reuse"):
        await tracker.refresh_if_stale()
    assert tracker.get_client()._ak_id == "ak-1"

    # Second refresh, with no further file change: the change is retried and the
    # new identity is picked up instead of being silently dropped.
    assert await tracker.refresh_if_stale() == gen0 + 1
    assert tracker.get_client()._ak_id == "ak-2"


@pytest.mark.asyncio
async def test_cli_profile_disabled_is_noop(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')
    tracker = CredentialTracker(
        profile_file=str(cfg), client_factory=_factory(["ak-1", "ak-2"])
    )
    gen0 = tracker.current_generation()
    monkeypatch.setattr(ct.au, "environment_cli_profile_disabled", "true")

    os.utime(str(cfg), (gen0 + 1000, gen0 + 1000))
    _write(str(cfg), '{"current":"b"}')
    assert await tracker.refresh_if_stale() == gen0


@pytest.mark.asyncio
async def test_default_watched_files_use_sdk_home(tmp_path, monkeypatch) -> None:
    """The CLI config.json path must come from the SDK's home resolver, not expanduser('~').

    On Windows the SDK prefers HOME over HOMEDRIVE/HOMEPATH while expanduser
    normally uses USERPROFILE, so watching expanduser('~') can monitor a
    different config.json than the one CredentialClient actually reads.
    """
    home = tmp_path / "sdk-home"
    (home / ".aliyun").mkdir(parents=True)
    cfg = home / ".aliyun" / "config.json"
    _write(str(cfg), '{"current":"a"}')

    monkeypatch.setattr(ct.ac, "HOME", str(home))
    monkeypatch.setattr(ct.au, "environment_credentials_file", None)

    tracker = CredentialTracker(client_factory=_factory(["ak-1", "ak-2"]))
    gen0 = tracker.current_generation()

    st = os.stat(str(cfg))
    os.utime(str(cfg), ns=(st.st_atime_ns + 10**9, st.st_mtime_ns + 10**9))
    _write(str(cfg), '{"current":"b"}')

    # A change under the SDK home is detected; if the tracker had used
    # expanduser('~') it would be watching a different file and miss this.
    assert await tracker.refresh_if_stale() == gen0 + 1


def test_default_watched_files_cover_cli_and_shared_profile(monkeypatch) -> None:
    """The default watched set is the CLI JSON (gated) plus the shared profile (ungated)."""
    monkeypatch.setattr(ct.ac, "HOME", "/fake/home")
    monkeypatch.setattr(ct.au, "environment_credentials_file", None)

    watched = ct._default_watched_files()

    assert watched == (
        (os.path.join("/fake/home", ".aliyun", "config.json"), True),
        (os.path.join("/fake/home", ".alibabacloud", "credentials.ini"), False),
    )

    # ALIBABA_CLOUD_CREDENTIALS_FILE overrides the shared profile path.
    monkeypatch.setattr(ct.au, "environment_credentials_file", "/custom/creds.ini")
    watched = ct._default_watched_files()
    assert watched[1] == ("/custom/creds.ini", False)


@pytest.mark.asyncio
async def test_shared_profile_file_change_is_detected(tmp_path) -> None:
    """A change to the lower-priority shared profile file must be detected too."""
    cli = tmp_path / "config.json"
    shared = tmp_path / "credentials.ini"
    _write(str(cli), '{"current":"a"}')
    _write(str(shared), "[default]\n")

    tracker = CredentialTracker(
        profile_files=[(str(cli), True), (str(shared), False)],
        client_factory=_factory(["ak-1", "ak-2"]),
    )
    gen0 = tracker.current_generation()

    st = os.stat(str(shared))
    os.utime(str(shared), ns=(st.st_atime_ns + 10**9, st.st_mtime_ns + 10**9))
    _write(str(shared), "[default]\nx=1\n")

    assert await tracker.refresh_if_stale() == gen0 + 1


@pytest.mark.asyncio
async def test_shared_profile_watched_when_cli_disabled(tmp_path, monkeypatch) -> None:
    """ALIBABA_CLOUD_CLI_PROFILE_DISABLED must gate only the CLI JSON, not the shared file."""
    cli = tmp_path / "config.json"
    shared = tmp_path / "credentials.ini"
    _write(str(cli), '{"current":"a"}')
    _write(str(shared), "[default]\n")

    tracker = CredentialTracker(
        profile_files=[(str(cli), True), (str(shared), False)],
        client_factory=_factory(["ak-1", "ak-2"]),
    )
    gen0 = tracker.current_generation()
    monkeypatch.setattr(ct.au, "environment_cli_profile_disabled", "true")

    # CLI config change is ignored while the CLI provider is disabled.
    st = os.stat(str(cli))
    os.utime(str(cli), ns=(st.st_atime_ns + 10**9, st.st_mtime_ns + 10**9))
    _write(str(cli), '{"current":"b"}')
    assert await tracker.refresh_if_stale() == gen0

    # The shared profile file stays watched regardless of the CLI flag.
    st = os.stat(str(shared))
    os.utime(str(shared), ns=(st.st_atime_ns + 10**9, st.st_mtime_ns + 10**9))
    _write(str(shared), "[default]\nx=1\n")
    assert await tracker.refresh_if_stale() == gen0 + 1


@pytest.mark.asyncio
async def test_rapid_replace_with_same_mtime_is_detected(tmp_path) -> None:
    """A rewrite that keeps the same mtime but changes size must still be detected.

    A float st_mtime gate would miss this on coarse-resolution or network
    filesystems; the composite (mtime_ns, size, inode) signature catches it.
    """
    cfg = tmp_path / "config.json"
    _write(str(cfg), '{"current":"a"}')  # 15 bytes
    tracker = CredentialTracker(
        profile_file=str(cfg), client_factory=_factory(["ak-1", "ak-2"])
    )
    gen0 = tracker.current_generation()

    st = os.stat(str(cfg))
    _write(str(cfg), '{"current":"bb"}')  # 16 bytes, different size
    # Pin mtime back to the exact original nanosecond timestamp.
    os.utime(str(cfg), ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.stat(str(cfg)).st_mtime_ns == st.st_mtime_ns  # mtime truly unchanged

    assert await tracker.refresh_if_stale() == gen0 + 1
