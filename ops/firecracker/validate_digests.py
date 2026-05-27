#!/usr/bin/env python3
"""Validate ops/firecracker/digests.json shape and reject placeholder digests."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIGESTS_PATH = REPO_ROOT / "ops" / "firecracker" / "digests.json"

SHAPE = re.compile(r"^sha256:[0-9a-f]{64}$")
PLACEHOLDER = re.compile(r"^sha256:([0-9a-f])\1{63}$")


def main() -> int:
    data = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key in ("rootfs", "lizard", "scc", "tree_sitter_core"):
        value = data.get(key)
        if not isinstance(value, str) or not SHAPE.fullmatch(value):
            errors.append(f"{key}: bad shape {value!r}")
        elif PLACEHOLDER.fullmatch(value):
            errors.append(f"{key}: placeholder {value!r}")
    grammars = data.get("grammars", {})
    for lang in ("python", "typescript"):
        value = grammars.get(lang)
        if not isinstance(value, str) or not SHAPE.fullmatch(value):
            errors.append(f"grammars.{lang}: bad shape {value!r}")
        elif PLACEHOLDER.fullmatch(value):
            errors.append(f"grammars.{lang}: placeholder {value!r}")
    if errors:
        for line in errors:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    print("OK: ops/firecracker/digests.json passes shape + placeholder checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
