"""Regenerate frozen tree-sitter span goldens for the grammar-stability gate.

Usage::

    uv run python scripts/regenerate_grammar_spans.py

Writes RFC 8785 canonical JSON bytes to ``tests/fixtures/grammar_spans/<name>.json``.
Re-running on an unchanged tree must produce a clean ``git diff`` — this is the
determinism contract enforced by ``tests/test_grammar_stability.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cce.canonical import canonical_json_bytes  # noqa: E402
from tests._grammar_spans import collect_spans  # noqa: E402

TARGETS: list[dict[str, str]] = [
    {
        "name": "simple_python",
        "language": "python",
        "source": "tests/fixtures/simple_python/pkg/example.py",
    },
    {
        "name": "simple_typescript",
        "language": "typescript",
        "source": "tests/fixtures/simple_typescript/src/example.ts",
    },
]

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "grammar_spans"


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        source_path = REPO_ROOT / target["source"]
        spans = collect_spans(source_path, target["language"])
        payload = {
            "source": target["source"],
            "language": target["language"],
            "spans": spans,
        }
        out_path = GOLDEN_DIR / f"{target['name']}.json"
        out_path.write_bytes(canonical_json_bytes(payload))
        print(f"wrote {out_path.relative_to(REPO_ROOT)} ({len(spans)} spans)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
