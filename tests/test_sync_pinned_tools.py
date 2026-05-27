"""Property tests for ``scripts/sync_pinned_tools.py``.

These tests guard the operator-controlled transformation that rewrites
``scoring-spec.yaml::pinned_tools`` (and recomputes ``spec_hash``) from
``ops/firecracker/digests.json``. They exercise the two universal
properties enumerated in the design document under "Correctness Properties".
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[1]

# Make ``scripts`` importable as a top-level package so we can call
# ``main()`` directly (task constraint: do NOT subprocess).
sys.path.insert(0, str(REPO_ROOT))

import scripts.sync_pinned_tools as sync_pinned_tools  # noqa: E402

SPEC_SOURCE = REPO_ROOT / "scoring-spec.yaml"

# Hypothesis strategy for one ``sha256:<64-lowercase-hex>`` digest.
_HEX_ALPHABET = "0123456789abcdef"
_sha256_digest = st.text(alphabet=_HEX_ALPHABET, min_size=64, max_size=64).map(
    lambda hex_string: f"sha256:{hex_string}"
)


def _digests_payload(
    lizard: str,
    scc: str,
    tree_sitter_core: str,
    grammar_python: str,
    grammar_typescript: str,
) -> dict:
    """Build a minimal valid ``digests.json`` payload."""
    return {
        "rootfs": "sha256:" + "0" * 64,  # informational; not consumed by sync
        "lizard": lizard,
        "scc": scc,
        "tree_sitter_core": tree_sitter_core,
        "grammars": {
            "python": grammar_python,
            "typescript": grammar_typescript,
        },
    }


def _stage_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    digests: dict,
) -> tuple[Path, Path]:
    """Copy the live ``scoring-spec.yaml`` into ``tmp_path`` and point the
    sync script at the staged copies via monkeypatched module paths."""
    spec_copy = tmp_path / "scoring-spec.yaml"
    digests_copy = tmp_path / "digests.json"
    shutil.copyfile(SPEC_SOURCE, spec_copy)
    digests_copy.write_text(json.dumps(digests), encoding="utf-8")
    monkeypatch.setattr(sync_pinned_tools, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_pinned_tools, "SPEC_PATH", spec_copy)
    monkeypatch.setattr(sync_pinned_tools, "DIGESTS_PATH", digests_copy)
    return spec_copy, digests_copy


# Feature: poc-readiness-hard-blockers, Property 1: sync_pinned_tools.py is idempotent
# Validates: Requirements 1.2, 1.3
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    lizard=_sha256_digest,
    scc=_sha256_digest,
    tree_sitter_core=_sha256_digest,
    grammar_python=_sha256_digest,
    grammar_typescript=_sha256_digest,
)
def test_sync_pinned_tools_is_idempotent(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    lizard: str,
    scc: str,
    tree_sitter_core: str,
    grammar_python: str,
    grammar_typescript: str,
) -> None:
    """For any valid ``digests.json`` (each digest matches
    ``^sha256:[0-9a-f]{64}$``), running ``sync_pinned_tools.main()`` twice
    against a fresh copy of ``scoring-spec.yaml`` SHALL produce
    byte-identical output."""
    tmp_path = tmp_path_factory.mktemp("sync_idempotence")
    digests = _digests_payload(
        lizard=lizard,
        scc=scc,
        tree_sitter_core=tree_sitter_core,
        grammar_python=grammar_python,
        grammar_typescript=grammar_typescript,
    )
    spec_copy, _digests_copy = _stage_workspace(tmp_path, monkeypatch, digests)

    assert sync_pinned_tools.main() == 0
    first_pass = spec_copy.read_bytes()

    assert sync_pinned_tools.main() == 0
    second_pass = spec_copy.read_bytes()

    assert first_pass == second_pass, (
        "sync_pinned_tools.main() must be idempotent: a second invocation "
        "against the same digests.json must produce byte-identical "
        "scoring-spec.yaml output"
    )


# Feature: poc-readiness-hard-blockers, Property 2: spec_hash round-trips
# Validates: Requirements 1.2, 1.3
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    lizard=_sha256_digest,
    scc=_sha256_digest,
    tree_sitter_core=_sha256_digest,
    grammar_python=_sha256_digest,
    grammar_typescript=_sha256_digest,
)
def test_sync_pinned_tools_spec_hash_round_trips(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    lizard: str,
    scc: str,
    tree_sitter_core: str,
    grammar_python: str,
    grammar_typescript: str,
) -> None:
    """For any valid ``digests.json``, after ``sync_pinned_tools.main()``
    rewrites ``scoring-spec.yaml``, loading the file via ``cce.spec.load_spec``
    SHALL succeed and the loaded ``spec_hash`` SHALL equal both the literal
    value in the YAML and ``"sha256:" + sha256(canonical_json_bytes(material)).hexdigest()``
    where ``material`` is the spec mapping with the ``spec_hash`` key removed.
    """
    import hashlib

    import yaml

    from cce.canonical import canonical_json_bytes
    from cce.spec import load_spec

    tmp_path = tmp_path_factory.mktemp("sync_round_trip")
    digests = _digests_payload(
        lizard=lizard,
        scc=scc,
        tree_sitter_core=tree_sitter_core,
        grammar_python=grammar_python,
        grammar_typescript=grammar_typescript,
    )
    spec_copy, _digests_copy = _stage_workspace(tmp_path, monkeypatch, digests)

    assert sync_pinned_tools.main() == 0

    raw = yaml.safe_load(spec_copy.read_text(encoding="utf-8"))
    yaml_value = raw["spec_hash"]
    material = {k: v for k, v in raw.items() if k != "spec_hash"}
    recomputed = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    )
    loaded = load_spec(spec_copy)

    assert yaml_value == recomputed, (
        f"YAML spec_hash {yaml_value!r} != locally recomputed {recomputed!r}"
    )
    assert loaded.spec_hash == recomputed, (
        f"load_spec.spec_hash {loaded.spec_hash!r} != recomputed {recomputed!r}"
    )
