"""PREQ-A-1: digest verification before each analyzer invocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from cce.analyzer import analyse_repo
from cce.analyzers.registry import (
    BackendEntry,
    default_registry,
)
from cce.runtime import (
    ToolDigestMismatchError,
    assert_tool_digest,
    compute_file_sha256,
)


def test_compute_file_sha256_roundtrip(tmp_path: Path) -> None:
    payload = tmp_path / "bin"
    payload.write_bytes(b"hello\n")
    assert (
        compute_file_sha256(payload)
        == "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


def test_assert_tool_digest_accepts_match(tmp_path: Path) -> None:
    payload = tmp_path / "lizard"
    payload.write_bytes(b"pretend-lizard-binary")
    digest = compute_file_sha256(payload)
    assert_tool_digest(name="lizard", expected_digest=digest, binary_path=payload)


def test_assert_tool_digest_rejects_tamper(tmp_path: Path) -> None:
    payload = tmp_path / "scc"
    payload.write_bytes(b"pretend-scc-binary")
    digest = compute_file_sha256(payload)
    payload.write_bytes(b"pretend-scc-binary-tampered")
    with pytest.raises(ToolDigestMismatchError):
        assert_tool_digest(name="scc", expected_digest=digest, binary_path=payload)


def test_assert_tool_digest_rejects_malformed() -> None:
    with pytest.raises(ToolDigestMismatchError):
        assert_tool_digest(
            name="lizard", expected_digest="not-a-digest", binary_path=Path("/dev/null")
        )


def test_assert_tool_digest_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(ToolDigestMismatchError):
        assert_tool_digest(
            name="lizard",
            expected_digest="sha256:" + "0" * 64,
            binary_path=tmp_path / "missing",
        )


def test_registry_assert_digests_blocks_analyse_repo(tmp_path: Path) -> None:
    """When the spec carries a pinned digest, a tampered binary must reject
    *before* any source file is touched."""
    fake_binary = tmp_path / "lizard"
    fake_binary.write_bytes(b"pinned-lizard")
    expected = compute_file_sha256(fake_binary)
    fake_binary.write_bytes(b"tampered-lizard")

    registry = default_registry()
    registry.register(
        language="python",
        entry=BackendEntry(
            name="lizard",
            backend=lambda src, text: {
                "cyclomatic": 0,
                "cognitive": 0,
                "nesting_depth": 0,
                "function_length": 0,
                "file_length": 0,
            },
            tool_digest_key="lizard",
            binary_resolver=lambda: fake_binary,
        ),
        default=True,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n")

    with pytest.raises(ToolDigestMismatchError):
        analyse_repo(repo, registry=registry, tool_digests={"lizard": expected})
