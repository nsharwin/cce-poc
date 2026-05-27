"""PREQ-A-4: grammar-stability gate.

Asserts that re-parsing each fixture produces byte-identical RFC 8785 canonical
JSON spans vs the frozen golden under ``tests/fixtures/grammar_spans/``.

To regenerate goldens after an intentional dependency bump::

    CCE_UPDATE_GRAMMAR_GOLDENS=1 uv run pytest tests/test_grammar_stability.py

The test deliberately fails after rewriting a golden so the run cannot be
silently green with stale bytes — re-run without the env var to confirm.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cce.canonical import canonical_json_bytes
from tests._grammar_spans import collect_spans

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "grammar_spans"

_CASES = [
    pytest.param(
        "simple_python",
        "python",
        "tests/fixtures/simple_python/pkg/example.py",
        id="python",
    ),
    pytest.param(
        "simple_typescript",
        "typescript",
        "tests/fixtures/simple_typescript/src/example.ts",
        id="typescript",
    ),
]


@pytest.mark.parametrize(("name", "language", "source"), _CASES)
def test_grammar_spans_match_golden(name: str, language: str, source: str) -> None:
    source_path = REPO_ROOT / source
    golden_path = GOLDEN_DIR / f"{name}.json"

    spans = collect_spans(source_path, language)
    payload = {"source": source, "language": language, "spans": spans}
    actual_bytes = canonical_json_bytes(payload)

    if not golden_path.exists():
        pytest.fail(f"golden missing: {golden_path}")

    expected_bytes = golden_path.read_bytes()
    if actual_bytes == expected_bytes:
        return

    if os.environ.get("CCE_UPDATE_GRAMMAR_GOLDENS") == "1":
        golden_path.write_bytes(actual_bytes)
        pytest.fail(
            f"golden updated for {name}: re-run without CCE_UPDATE_GRAMMAR_GOLDENS "
            f"to confirm green ({len(spans)} spans → {golden_path})"
        )

    pytest.fail(
        "grammar-stability drift detected\n"
        f"  fixture: {source_path}\n"
        f"  golden : {golden_path}\n"
        f"  spans  : {len(spans)} (actual) vs golden size {len(expected_bytes)} bytes\n"
        "  to regenerate: CCE_UPDATE_GRAMMAR_GOLDENS=1 uv run pytest "
        "tests/test_grammar_stability.py"
    )
