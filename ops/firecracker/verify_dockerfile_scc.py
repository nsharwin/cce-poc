#!/usr/bin/env python3
"""Verify Dockerfile ARG SCC_SHA256 == bare-hex(scoring-spec.yaml::pinned_tools.scc)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
SPEC = REPO_ROOT / "scoring-spec.yaml"

ARG_RE = re.compile(r"^ARG\s+SCC_SHA256=([0-9a-f]+)\s*$", re.MULTILINE)


def main() -> int:
    arg_match = ARG_RE.search(DOCKERFILE.read_text(encoding="utf-8"))
    if not arg_match:
        print("FAIL: Dockerfile ARG SCC_SHA256 not found or malformed", file=sys.stderr)
        return 1
    arg_value = arg_match.group(1)
    if arg_value == "0" * 64:
        print("FAIL: ARG SCC_SHA256 is all zeros (placeholder)", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[0-9a-f]{64}", arg_value):
        print(f"FAIL: ARG SCC_SHA256={arg_value!r} bad shape", file=sys.stderr)
        return 1

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    scc_digest = spec["pinned_tools"]["scc"]
    expected_arg = scc_digest.removeprefix("sha256:")

    print(f"Dockerfile ARG SCC_SHA256:  {arg_value}")
    print(f"Spec pinned_tools.scc:      {scc_digest}")
    print(f"Bare-hex form:              {expected_arg}")
    if arg_value != expected_arg:
        print("FAIL: ARG SCC_SHA256 != bare-hex(pinned_tools.scc)", file=sys.stderr)
        return 1
    print("OK: Dockerfile SCC_SHA256 matches scoring-spec.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
