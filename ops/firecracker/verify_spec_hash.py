#!/usr/bin/env python3
"""Verify Property 2: spec_hash in scoring-spec.yaml round-trips through cce.spec.load_spec."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cce.canonical import canonical_json_bytes  # noqa: E402
from cce.spec import load_spec  # noqa: E402

SPEC_PATH = REPO_ROOT / "scoring-spec.yaml"


def main() -> int:
    raw = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    yaml_value = raw["spec_hash"]
    material = {k: v for k, v in raw.items() if k != "spec_hash"}
    recomputed = "sha256:" + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    loaded = load_spec(SPEC_PATH)
    print(f"yaml spec_hash:       {yaml_value}")
    print(f"recomputed locally:   {recomputed}")
    print(f"load_spec.spec_hash:  {loaded.spec_hash}")
    if yaml_value != recomputed or recomputed != loaded.spec_hash:
        print("FAIL: spec_hash mismatch", file=sys.stderr)
        return 1
    print("OK: spec_hash round-trips through load_spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
