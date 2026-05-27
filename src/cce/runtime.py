"""PREQ-A-3 runtime network-isolation self-check.

We do NOT enforce network isolation from Python — that is the Docker
boundary's job (``docker run --network=none``). This module only *probes*
whether egress is reachable so CCE can fail fast when the operator
asserts (via ``--assert-network-isolated`` or
``CCE_REQUIRE_NETWORK_ISOLATED=1``) that the boundary should be in effect.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
from pathlib import Path


class NetworkIsolationError(RuntimeError):
    pass


class ToolDigestMismatchError(RuntimeError):
    """Raised when a pinned analyzer binary does not match its expected digest.

    Triggered before each invocation of a digest-pinned backend (``lizard``,
    ``scc``) so a tampered or wrong-arch binary is rejected before any
    untrusted source is touched (PREQ-A-1).
    """


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def compute_file_sha256(path: Path) -> str:
    """Return ``sha256:<hex>`` for the bytes of ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def assert_tool_digest(
    *,
    name: str,
    expected_digest: str,
    binary_path: Path,
) -> None:
    """Compare ``binary_path``'s sha256 against ``expected_digest``.

    Raises :class:`ToolDigestMismatchError` on any mismatch, missing file, or
    malformed digest string. Used by ``AnalyzerRegistry.assert_digests``
    before each analyzer call.
    """
    if not _DIGEST_RE.match(expected_digest):
        raise ToolDigestMismatchError(
            f"{name}: expected digest must match 'sha256:<64 lowercase hex>'"
        )
    binary_path = Path(binary_path)
    if not binary_path.is_file():
        raise ToolDigestMismatchError(f"{name}: pinned binary not found at {binary_path}")
    actual = compute_file_sha256(binary_path)
    if actual != expected_digest:
        raise ToolDigestMismatchError(
            f"{name}: digest mismatch at {binary_path}; expected {expected_digest}, got {actual}"
        )


def is_network_isolated(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.0) -> bool:
    """Return True iff a TCP connect to ``(host, port)`` fails within ``timeout``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except (TimeoutError, OSError):
        return True
    else:
        return False
    finally:
        sock.close()


def assert_network_isolated() -> None:
    """Raise :class:`NetworkIsolationError` if network egress is reachable.

    Triggered by the ``--assert-network-isolated`` CLI flag or the
    ``CCE_REQUIRE_NETWORK_ISOLATED=1`` env var.
    """
    if not is_network_isolated():
        raise NetworkIsolationError(
            "network egress reachable; refusing to run under "
            "CCE_REQUIRE_NETWORK_ISOLATED=1 / --assert-network-isolated"
        )


def assert_network_isolated_if_required() -> None:
    if os.environ.get("CCE_REQUIRE_NETWORK_ISOLATED") == "1":
        assert_network_isolated()
