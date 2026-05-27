#!/usr/bin/env python3
"""Sync `scoring-spec.yaml::pinned_tools` from `ops/firecracker/digests.json`.

This script is the single source of truth for translating the digests baked
into the production rootfs into the spec consumed by the deterministic
scoring core.

Workflow:

    1. Operator runs `ops/firecracker/rootfs.build.sh`. That script computes
       sha256 of each pinned binary (`lizard`, `scc`, `tree_sitter` core lib,
       grammar `.so` files) inside the built rootfs and emits
       `ops/firecracker/digests.json`.
    2. Operator runs `python scripts/sync_pinned_tools.py`. This rewrites
       `scoring-spec.yaml::pinned_tools` deterministically so the spec's
       digests match the rootfs.
    3. Operator commits the resulting `scoring-spec.yaml` change. `spec_hash`
       (and therefore `record_hash`) shifts in a single audited commit.

The script is intentionally minimal: it patches only the `pinned_tools`
subtree, preserves the surrounding YAML, and is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGESTS_PATH = REPO_ROOT / "ops" / "firecracker" / "digests.json"
SPEC_PATH = REPO_ROOT / "scoring-spec.yaml"

# Reuse RFC 8785 canonicalisation from the cce package; do NOT re-implement.
sys.path.insert(0, str(REPO_ROOT / "src"))
from cce.canonical import canonical_json_bytes  # noqa: E402


def _load_digests() -> dict:
    if not DIGESTS_PATH.is_file():
        raise SystemExit(
            f"missing {DIGESTS_PATH}; run ops/firecracker/rootfs.build.sh first"
        )
    return json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))


def _validate(digests: dict) -> None:
    required = {"lizard", "scc", "tree_sitter_core", "grammars"}
    missing = required - set(digests)
    if missing:
        raise SystemExit(f"digests.json missing keys: {sorted(missing)}")
    for key in ("lizard", "scc", "tree_sitter_core"):
        value = digests[key]
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise SystemExit(f"digests.json[{key!r}] must be 'sha256:<hex>'")
    grammars = digests["grammars"]
    if not isinstance(grammars, dict) or not grammars:
        raise SystemExit("digests.json['grammars'] must be a non-empty object")
    for lang, value in grammars.items():
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise SystemExit(f"digests.json['grammars'][{lang!r}] must be 'sha256:<hex>'")


def main() -> int:
    digests = _load_digests()
    _validate(digests)

    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    spec = yaml.safe_load(spec_text)

    spec["pinned_tools"] = {
        "tree_sitter_core": digests["tree_sitter_core"],
        "grammars": dict(sorted(digests["grammars"].items())),
        "lizard": digests["lizard"],
        "scc": digests["scc"],
    }

    new_text = yaml.safe_dump(spec, sort_keys=False, default_flow_style=False)
    SPEC_PATH.write_text(new_text, encoding="utf-8")

    # Recompute spec_hash over the canonicalised spec content (excluding the
    # spec_hash field itself), matching cce.spec._compute_spec_hash exactly so
    # the committed value round-trips through cce.spec.load_spec. Re-reading
    # the just-written file keeps this idempotent: a second invocation against
    # the same digests.json produces byte-identical scoring-spec.yaml output.
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    material = {k: v for k, v in spec.items() if k != "spec_hash"}
    spec["spec_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    SPEC_PATH.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    print(f"updated {SPEC_PATH.relative_to(REPO_ROOT)} from {DIGESTS_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
