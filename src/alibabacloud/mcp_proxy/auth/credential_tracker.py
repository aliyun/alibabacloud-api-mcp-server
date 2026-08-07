from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

import anyio
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.utils import auth_constant as ac
from alibabacloud_credentials.utils import auth_util as au

_LOGGER = logging.getLogger(__name__)

# A file signature that survives coarse-resolution and network filesystems:
# a float ``st_mtime`` alone can stay identical across rapid rewrites (FAT, some
# network/container mounts). The credential SDK also swaps files via
# ``os.replace``, so pairing the nanosecond mtime with the size and inode makes
# an atomic replacement observable even when the timestamp looks unchanged.
FileSignature = tuple[int, int, int]


class CredentialRefreshError(RuntimeError):
    """Raised when changed profile files cannot produce usable credentials."""


def _sdk_home() -> str:
    """Resolve the home directory exactly as the credential SDK does.

    ``os.path.expanduser("~")`` does not necessarily select the same directory
    as ``alibabacloud-credentials`` on Windows: the SDK prefers ``HOME`` before
    ``HOMEDRIVE``/``HOMEPATH``, whereas Windows ``expanduser`` normally uses
    ``USERPROFILE``. Reusing the SDK's own resolver guarantees the tracker
    watches the very file ``CredentialClient`` reads (Git Bash, portable and
    some CI environments can otherwise diverge).
    """
    # Credential providers build their profile paths from ``auth_constant.HOME``,
    # which is resolved once when the SDK is imported. Use the same cached value
    # so an in-process environment mutation cannot make the tracker and SDK read
    # different directories.
    return ac.HOME


def _default_watched_files() -> tuple[tuple[str, bool], ...]:
    """Default profile files to watch, each tagged whether the CLI-disabled flag applies.

    Mirrors the default credential chain's file-backed providers:

    * ``~/.aliyun/config.json`` — the Alibaba Cloud CLI profile (higher
      priority). Gated by ``ALIBABA_CLOUD_CLI_PROFILE_DISABLED``.
    * ``$ALIBABA_CLOUD_CREDENTIALS_FILE`` or ``~/.alibabacloud/credentials.ini``
      — the shared "Profile" provider (lower priority). NOT gated by the CLI
      flag.

    Both are watched; the SDK's chain still decides which file actually supplies
    the effective credentials, so watching both honours the priority order while
    detecting a higher-priority file appearing, disappearing, or switching.
    """
    home = _sdk_home()
    cli_config = os.path.join(home, ".aliyun", "config.json")
    shared_profile = au.environment_credentials_file or os.path.join(
        home, ".alibabacloud", "credentials.ini"
    )
    return ((cli_config, True), (shared_profile, False))


def _cli_profile_disabled() -> bool:
    # Match CLIProfileCredentialsProvider, which reads the value cached by the
    # SDK at import time rather than consulting os.environ on every request.
    return au.environment_cli_profile_disabled.strip().lower() == "true"


def _file_signature(path: str) -> FileSignature | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _resolve_ak_id(client: Any) -> str | None:
    """Resolve the current access key id, swallowing any failure (returns None)."""
    try:
        credential = client.get_credential()
        ak_id = credential.get_access_key_id()
    except Exception as exc:  # network/parse/credential errors must not break requests
        _LOGGER.debug("Credential resolve failed: %s", exc)
        return None
    return ak_id or None


class CredentialTracker:
    """Owns a rebuildable CredentialClient and detects local default-credential switches.

    Detection is lazy: callers invoke ``refresh_if_stale`` per request. A cheap
    per-file signature gate avoids rebuilding/re-resolving in the steady state.
    The resolved access key id is the identity fingerprint; when it changes the
    client is rebuilt and ``generation`` is bumped so downstream token/connection
    caches self-invalidate.

    The watched set covers the file-backed providers of the SDK default chain
    (the CLI ``config.json`` and the shared profile file). Non-file providers of
    the chain (environment variables, OIDC token files, ECS, credentials URI)
    are not watched here — they refresh through their own mechanisms.
    """

    def __init__(
        self,
        *,
        profile_file: str | None = None,
        profile_files: Sequence[tuple[str, bool]] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        if profile_files is not None:
            watched = tuple(profile_files)
        elif profile_file is not None:
            # Legacy single-file form: treated as the CLI profile (config.json),
            # so it is gated by ALIBABA_CLOUD_CLI_PROFILE_DISABLED.
            watched = ((profile_file, True),)
        else:
            watched = _default_watched_files()
        self._watched = watched
        self._client_factory = client_factory or (lambda: CredentialClient())
        self._lock = anyio.Lock()
        self._client = self._client_factory()
        self._generation = 1
        self._last_signatures: dict[str, FileSignature | None] = {
            path: _file_signature(path) for path, _ in self._watched
        }
        self._last_ak_id = _resolve_ak_id(self._client)

    def get_client(self) -> Any:
        return self._client

    def current_generation(self) -> int:
        return self._generation

    def _active_files(self) -> list[str]:
        """Files whose changes should trigger a re-evaluation right now.

        The CLI profile file is dropped while ``ALIBABA_CLOUD_CLI_PROFILE_DISABLED``
        is set — the SDK skips its provider entirely in that case — but the
        shared profile file stays watched regardless of the CLI flag.
        """
        disabled = _cli_profile_disabled()
        return [path for path, cli_gated in self._watched if not (cli_gated and disabled)]

    async def refresh_if_stale(self) -> int:
        async with self._lock:
            active = self._active_files()
            current = {path: _file_signature(path) for path in active}
            if all(current[path] == self._last_signatures.get(path) for path in active):
                return self._generation

            # A watched file changed (or (re)appeared/disappeared): re-evaluate.
            new_client = self._client_factory()
            new_ak_id = _resolve_ak_id(new_client)
            if new_ak_id is None:
                # Do not advance the file signatures, so a transient failure is
                # retried on the next request. More importantly, fail this request
                # instead of silently continuing with credentials that the user
                # just removed or replaced.
                raise CredentialRefreshError(
                    "Local credential profile changed but the new credentials "
                    "could not be resolved; refusing to reuse the previous identity."
                )

            # Resolution succeeded: commit the observed signatures now.
            self._last_signatures.update(current)

            if new_ak_id != self._last_ak_id:
                _LOGGER.info("Local default credential switched; rebuilding client.")
                self._client = new_client
                self._last_ak_id = new_ak_id
                self._generation += 1

            return self._generation
