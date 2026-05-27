"""Real-digest invariants across digests.json, scoring-spec.yaml, and Dockerfile.

Spec: poc-readiness-hard-blockers, task 1.10.
Validates Requirements 1.1 (no placeholder digests), 4.1, 4.2, 4.3 (Dockerfile
SCC_SHA256 == bare-hex of pinned_tools.scc, neither all-zero nor malformed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from cce.spec import load_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGESTS_PATH = REPO_ROOT / "ops" / "firecracker" / "digests.json"
SPEC_PATH = REPO_ROOT / "scoring-spec.yaml"
DOCKERFILE = REPO_ROOT / "Dockerfile"

SHA256_PREFIXED = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_BARE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_PREFIXED = re.compile(r"^sha256:([0-9a-f])\1{63}$")
PLACEHOLDER_BARE = re.compile(r"^([0-9a-f])\1{63}$")
ARG_RE = re.compile(r"^ARG\s+SCC_SHA256=([0-9a-f]+)\s*$", re.MULTILINE)


def _load_digests() -> dict:
    return json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))


def test_digests_json_has_no_placeholders() -> None:
    """Every operational digest in digests.json is real, well-shaped, non-placeholder.

    The `rootfs` key is informational (sidecar of cce-rootfs.ext4) and is not
    consumed by sync_pinned_tools.py; it is included here to satisfy the
    audit's intent that no key in digests.json carries a placeholder value.
    """
    digests = _load_digests()
    flat = {
        "lizard": digests["lizard"],
        "scc": digests["scc"],
        "tree_sitter_core": digests["tree_sitter_core"],
        "rootfs": digests["rootfs"],
        "grammars.python": digests["grammars"]["python"],
        "grammars.typescript": digests["grammars"]["typescript"],
    }
    for key, value in flat.items():
        assert SHA256_PREFIXED.fullmatch(value), f"{key}: bad shape {value!r}"
        assert not PLACEHOLDER_PREFIXED.fullmatch(
            value
        ), f"{key}: placeholder digest {value!r}"


def test_scoring_spec_pinned_tools_match_digests_json() -> None:
    """Scoring_Spec.tool_digests equals corresponding entries in digests.json."""
    digests = _load_digests()
    spec = load_spec(SPEC_PATH)
    flat_expected = {
        "lizard": digests["lizard"],
        "scc": digests["scc"],
        "tree_sitter_core": digests["tree_sitter_core"],
        "tree_sitter_python": digests["grammars"]["python"],
        "tree_sitter_typescript": digests["grammars"]["typescript"],
    }
    for tool, expected in flat_expected.items():
        actual = spec.tool_digests.get(tool)
        assert actual == expected, (
            f"{tool}: scoring-spec.yaml has {actual!r}, "
            f"digests.json has {expected!r}"
        )


def test_dockerfile_scc_matches_scoring_spec() -> None:
    """Dockerfile ARG SCC_SHA256 default == bare-hex(pinned_tools.scc)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = ARG_RE.search(text)
    assert match is not None, "ARG SCC_SHA256=<hex> not found in Dockerfile"
    arg_value = match.group(1)

    raw = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    spec_value = raw["pinned_tools"]["scc"]
    assert spec_value.startswith("sha256:"), spec_value
    expected_arg = spec_value.removeprefix("sha256:")
    assert arg_value == expected_arg, (
        f"Dockerfile SCC_SHA256={arg_value!r} != "
        f"bare-hex(pinned_tools.scc)={expected_arg!r}"
    )


def test_dockerfile_scc_is_not_zero() -> None:
    """Dockerfile SCC_SHA256 default is a real digest (not 64 zeros)."""
    match = ARG_RE.search(DOCKERFILE.read_text(encoding="utf-8"))
    assert match is not None
    arg_value = match.group(1)
    assert SHA256_BARE.fullmatch(arg_value), f"bad shape: {arg_value!r}"
    assert arg_value != "0" * 64, "ARG SCC_SHA256 is the placeholder all-zero default"
    assert not PLACEHOLDER_BARE.fullmatch(
        arg_value
    ), f"ARG SCC_SHA256 is a placeholder pattern: {arg_value!r}"
