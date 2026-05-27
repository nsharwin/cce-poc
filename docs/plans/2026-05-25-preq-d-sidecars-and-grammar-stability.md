# PREQ-D Sidecars + PREQ-A-4 Grammar Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock down two POC-PRD quick-wins on top of the work already shipped: (a) add focused tests that pin the `<record_hash>.raw.json` (PREQ-D-2) and `<record_hash>.sha256` (PREQ-D-3) sidecar contract emitted by `cli.py::_write_outputs`, and (b) add a tree-sitter grammar-stability gate (PREQ-A-4) that freezes per-fixture named-node spans into a golden JSON file and asserts byte-identical re-parses on every CI run.

**Architecture:**
1. **PREQ-D-2 / PREQ-D-3** — the sidecar files are already written by `src/cce/cli.py::_write_outputs` (existing `.json`, `.raw.json`, `.sha256`). The gap is verification: `tests/test_cli.py::test_score_cli_writes_record_raw_and_sha256_files` only checks existence. We add one tightly-scoped test that asserts (i) `.raw.json` is RFC 8785 canonical bytes of a payload with sorted per-file entries, and (ii) `.sha256` content is exactly `sha256:<hex>\n` where the hex is `sha256(canonical_json_bytes(record))`. No production-code changes required unless the test surfaces a defect — if it does, the fix is a ≤5-line tweak in `_write_outputs`.
2. **PREQ-A-4** — add a tiny TS fixture next to the existing Python fixture, build a deterministic walker over tree-sitter *named* nodes for each fixture file (`(type, start_byte, end_byte, start_point, end_point)`), and freeze the result into `tests/fixtures/grammar_spans/<name>.json`. A new `tests/test_grammar_stability.py` re-parses the fixtures on every run and asserts byte-identical equality against the frozen golden. A `--update-goldens` env-var escape hatch makes future intentional grammar bumps a one-command operation.

**Tech Stack:** Python 3.12, uv, pytest 9.0.3, `tree-sitter==0.24.0`, `tree-sitter-language-pack==0.7.2`, `rfc8785==0.1.4`, `hashlib` (stdlib).

---

## File Structure

**Creates:**
- `tests/fixtures/simple_typescript/src/example.ts` — small TS fixture (one arrow fn, one async fn, one class method, `if/else/&&`).
- `tests/fixtures/grammar_spans/simple_python.json` — frozen tree-sitter spans for `tests/fixtures/simple_python/pkg/example.py`.
- `tests/fixtures/grammar_spans/simple_typescript.json` — frozen tree-sitter spans for the new TS fixture.
- `tests/test_grammar_stability.py` — PREQ-A-4 test that walks each fixture and compares to golden.
- `tests/_grammar_spans.py` — small helper module exposing `collect_spans(path: Path, language: str) -> list[dict]`. Kept private (underscore) and shared by both the test and the regeneration script.
- `scripts/regenerate_grammar_spans.py` — operator-facing regeneration script (idempotent; writes RFC 8785 canonical JSON).

**Modifies:**
- `tests/test_cli.py` — add **one** new test `test_sidecar_files_have_canonical_contents` (PREQ-D-2 + PREQ-D-3). Existing tests are not touched.
- `.github/workflows/poc-determinism.yml` — no change required (the new test runs under the existing `uv run pytest -q` step). Listed here only to confirm the omission is intentional.

**Does NOT touch:**
- `src/cce/cli.py`, `src/cce/scoring.py`, `src/cce/analyzer.py`, `src/cce/canonical.py` — unless Task 1 surfaces a real defect.

---

## Task 1: PREQ-D-2 + PREQ-D-3 — Sidecar Contract Test

**Why:** PRD `PREQ-D-2` requires `./cce-out/<record_hash>.raw.json` (raw analyzer payload, reproducibility audit). `PREQ-D-3` requires `./cce-out/<record_hash>.sha256` (sha256 of the JSON for tamper detection). `_write_outputs` already writes both, but the only test currently asserts existence + top-level keys. We need to lock in the **exact byte contract** so a future refactor cannot silently break tamper detection.

**Files:**
- Modify: `tests/test_cli.py` — append one new test after `test_score_cli_writes_record_raw_and_sha256_files` (around line 86).

- [ ] **Step 1: Write the failing test**

Append this test to `tests/test_cli.py` (it reuses the existing `make_fixture_repo` + `write_sample_spec` helpers already imported in the file):

```python
def test_sidecar_files_have_canonical_contents(tmp_path: Path, capsys) -> None:
    """PREQ-D-2 / PREQ-D-3: raw.json is canonical JCS, sha256 file matches sha256(record.json bytes)."""
    import hashlib

    from cce.canonical import canonical_json_bytes

    repo, commit_sha = make_fixture_repo(tmp_path)
    spec_path = tmp_path / "scoring-spec.yaml"
    out_dir = tmp_path / "cce-out"
    write_sample_spec(spec_path)

    exit_code = main(
        [
            "score",
            "--spec", str(spec_path),
            "--repo", str(repo),
            "--mode", "commit",
            "--commit", commit_sha,
            "--out", str(out_dir),
            "--verify-digests", "false",
        ]
    )
    assert exit_code == 0
    record_hash = capsys.readouterr().out.strip()

    record_path = out_dir / f"{record_hash}.json"
    raw_path = out_dir / f"{record_hash}.raw.json"
    sha_path = out_dir / f"{record_hash}.sha256"

    # PREQ-D-1: record JSON is canonical (RFC 8785 JCS) bytes.
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes)
    assert record_bytes == canonical_json_bytes(record), "record JSON must be RFC 8785 canonical"

    # PREQ-D-2: raw payload is canonical and per-file entries are sorted by `path` ascending.
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    assert raw_bytes == canonical_json_bytes(raw), "raw JSON must be RFC 8785 canonical"
    assert set(raw) == {"files", "summary"}
    paths = [entry["path"] for entry in raw["files"]]
    assert paths == sorted(paths), f"raw['files'] must be sorted by path, got {paths}"
    for entry in raw["files"]:
        assert set(entry) >= {"path", "language", "metrics"}

    # PREQ-D-3: sidecar is exactly `sha256:<hex>\n` of the canonical record JSON bytes.
    expected_digest = hashlib.sha256(record_bytes).hexdigest()
    sha_text = sha_path.read_text(encoding="utf-8")
    assert sha_text == f"sha256:{expected_digest}\n", (
        f"sha256 sidecar contract violated: got {sha_text!r}"
    )
```

- [ ] **Step 2: Run the test to confirm it passes today (sanity)**

Run: `uv run pytest tests/test_cli.py::test_sidecar_files_have_canonical_contents -v`

Expected: **PASS** (because `_write_outputs` already conforms). If it fails, the failure pinpoints the contract drift — fix it in `src/cce/cli.py::_write_outputs` with the minimum change required, then re-run. Do **not** rewrite the test to match buggy output.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `uv run pytest -q`

Expected: `14 passed` (13 existing + 1 new).

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: pin raw.json + sha256 sidecar byte contract (PREQ-D-2, PREQ-D-3)"
```

---

## Task 2: PREQ-A-4 — Add a TypeScript Fixture

**Why:** Only `tests/fixtures/simple_python/` exists today. PREQ-A-4 says "parse the golden corpus" (plural) and the parent PRD's POC scope explicitly lists both `python` and `typescript`. The TS fixture also stresses the new tree-sitter TS analyzer added in `2026-05-24-three-high-value-items.md`. Keep it tiny and stable — large fixtures invite churn and grammar-version flakiness.

**Files:**
- Create: `tests/fixtures/simple_typescript/src/example.ts`

- [ ] **Step 1: Create the TS fixture directory**

Run: `mkdir -p tests/fixtures/simple_typescript/src`

- [ ] **Step 2: Write the fixture file**

Create `tests/fixtures/simple_typescript/src/example.ts` with **exactly** this content (note: trailing newline, LF line endings, 2-space indent — required for stable byte spans):

```typescript
export type Score = { value: number; label: string };

export function classify(score: Score): string {
  if (score.value > 10 && score.label !== "") {
    return "high";
  } else if (score.value > 5) {
    return "mid";
  }
  return "low";
}

export const sumPositive = (values: number[]): number => {
  let total = 0;
  for (const v of values) {
    if (v > 0) {
      total += v;
    }
  }
  return total;
};
```

- [ ] **Step 3: Verify LF line endings and trailing newline**

Run: `file tests/fixtures/simple_typescript/src/example.ts && od -c tests/fixtures/simple_typescript/src/example.ts | tail -1`

Expected: file reports `ASCII text` (NOT `with CRLF line terminators`); last `od` line shows a trailing `\n`.

- [ ] **Step 4: Commit (no test yet — fixture only)**

```bash
git add tests/fixtures/simple_typescript/
git commit -m "test: add minimal TypeScript fixture for grammar-stability gate (PREQ-A-4)"
```

---

## Task 3: PREQ-A-4 — Shared Span-Collection Helper

**Why:** The test and the regeneration script both need identical traversal logic. A separate helper keeps the test focused and ensures `tests/test_grammar_stability.py` and `scripts/regenerate_grammar_spans.py` cannot drift apart.

**Files:**
- Create: `tests/_grammar_spans.py`

- [ ] **Step 1: Write the helper**

Create `tests/_grammar_spans.py` with this content:

```python
"""Deterministic tree-sitter span collection used by PREQ-A-4 grammar-stability tests.

Walks **named** nodes only (skips anonymous syntactic tokens) in document order and
emits a list of dicts with stable, byte-exact identity:

    {
        "type":       <node.type>,
        "start_byte": <int>,
        "end_byte":   <int>,
        "start_row":  <int>,   # 0-based
        "start_col":  <int>,   # 0-based byte column
        "end_row":    <int>,
        "end_col":    <int>,
    }

Document order = pre-order DFS over `node.children` (tree-sitter children are returned
in source order, so no explicit sort is needed). Anonymous tokens are excluded because
their identity is grammar-version-sensitive; named nodes are what our analyzer relies on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tree_sitter_language_pack
from tree_sitter import Node, Parser


def collect_spans(path: Path, language: str) -> list[dict[str, Any]]:
    text = path.read_bytes()
    parser = Parser(tree_sitter_language_pack.get_language(language))
    tree = parser.parse(text)
    spans: list[dict[str, Any]] = []
    _walk(tree.root_node, spans)
    return spans


def _walk(node: Node, out: list[dict[str, Any]]) -> None:
    if node.is_named:
        start_row, start_col = node.start_point
        end_row, end_col = node.end_point
        out.append(
            {
                "type": node.type,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "start_row": start_row,
                "start_col": start_col,
                "end_row": end_row,
                "end_col": end_col,
            }
        )
    for child in node.children:
        _walk(child, out)
```

- [ ] **Step 2: Smoke-check the helper in a one-liner**

Run:

```bash
uv run python -c "from pathlib import Path; from tests._grammar_spans import collect_spans; spans = collect_spans(Path('tests/fixtures/simple_python/pkg/example.py'), 'python'); print(len(spans), spans[0])"
```

Expected: prints a positive count and a dict whose `type` is `module` with `start_byte=0`.

- [ ] **Step 3: Commit**

```bash
git add tests/_grammar_spans.py
git commit -m "test: add deterministic tree-sitter span-collection helper (PREQ-A-4)"
```

---

## Task 4: PREQ-A-4 — Regeneration Script + Initial Golden Files

**Why:** Goldens must be regeneratable by a single, auditable command. The script lives in the repo (not the test) so reviewers can read the exact bytes that produced the golden.

**Files:**
- Create: `scripts/regenerate_grammar_spans.py`
- Create: `tests/fixtures/grammar_spans/simple_python.json`
- Create: `tests/fixtures/grammar_spans/simple_typescript.json`

- [ ] **Step 1: Write the regeneration script**

Create `scripts/regenerate_grammar_spans.py`:

```python
"""Regenerate PREQ-A-4 grammar-stability golden files.

Usage: `uv run python scripts/regenerate_grammar_spans.py`

Writes RFC 8785 canonical JSON so the golden bytes are byte-stable across machines.
Run after an intentional tree-sitter or grammar bump; commit the diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cce.canonical import canonical_json_bytes  # noqa: E402
from tests._grammar_spans import collect_spans  # noqa: E402

TARGETS: list[tuple[Path, str, str]] = [
    (
        REPO_ROOT / "tests/fixtures/simple_python/pkg/example.py",
        "python",
        "simple_python",
    ),
    (
        REPO_ROOT / "tests/fixtures/simple_typescript/src/example.ts",
        "typescript",
        "simple_typescript",
    ),
]

GOLDEN_DIR = REPO_ROOT / "tests/fixtures/grammar_spans"


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for source, language, name in TARGETS:
        spans = collect_spans(source, language)
        payload = {
            "source": source.relative_to(REPO_ROOT).as_posix(),
            "language": language,
            "spans": spans,
        }
        out_path = GOLDEN_DIR / f"{name}.json"
        out_path.write_bytes(canonical_json_bytes(payload))
        print(f"wrote {out_path.relative_to(REPO_ROOT)} ({len(spans)} named nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Generate the initial goldens**

Run: `uv run python scripts/regenerate_grammar_spans.py`

Expected output (counts will vary but both files must be written):

```
wrote tests/fixtures/grammar_spans/simple_python.json (<N> named nodes)
wrote tests/fixtures/grammar_spans/simple_typescript.json (<M> named nodes)
```

- [ ] **Step 3: Verify the goldens are canonical (re-running is a no-op)**

Run:

```bash
uv run python scripts/regenerate_grammar_spans.py && git diff --exit-code tests/fixtures/grammar_spans/
```

Expected: exit code 0 (no diff). If `git diff` shows changes, the helper is not deterministic — STOP and debug `tests/_grammar_spans.py` before continuing.

- [ ] **Step 4: Commit**

```bash
git add scripts/regenerate_grammar_spans.py tests/fixtures/grammar_spans/
git commit -m "test: freeze tree-sitter spans for python+typescript fixtures (PREQ-A-4)"
```

---

## Task 5: PREQ-A-4 — Grammar-Stability Test

**Why:** This is the actual PREQ-A-4 gate. It must FAIL loudly on any drift in tree-sitter or its grammars, and must offer an obvious recovery path (`CCE_UPDATE_GRAMMAR_GOLDENS=1`) for *intentional* bumps.

**Files:**
- Create: `tests/test_grammar_stability.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_grammar_stability.py`:

```python
"""PREQ-A-4: tree-sitter named-node spans MUST be byte-identical across runs/platforms.

Update goldens intentionally with:
    uv run python scripts/regenerate_grammar_spans.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cce.canonical import canonical_json_bytes
from tests._grammar_spans import collect_spans

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests/fixtures/grammar_spans"

CASES = [
    pytest.param(
        REPO_ROOT / "tests/fixtures/simple_python/pkg/example.py",
        "python",
        GOLDEN_DIR / "simple_python.json",
        id="python",
    ),
    pytest.param(
        REPO_ROOT / "tests/fixtures/simple_typescript/src/example.ts",
        "typescript",
        GOLDEN_DIR / "simple_typescript.json",
        id="typescript",
    ),
]


@pytest.mark.parametrize("source, language, golden", CASES)
def test_grammar_spans_match_golden(source: Path, language: str, golden: Path) -> None:
    assert source.is_file(), f"fixture missing: {source}"
    assert golden.is_file(), (
        f"golden missing: {golden}. Run "
        "`uv run python scripts/regenerate_grammar_spans.py`."
    )

    spans = collect_spans(source, language)
    actual_payload = {
        "source": source.relative_to(REPO_ROOT).as_posix(),
        "language": language,
        "spans": spans,
    }
    actual_bytes = canonical_json_bytes(actual_payload)
    golden_bytes = golden.read_bytes()

    if actual_bytes == golden_bytes:
        return

    if os.environ.get("CCE_UPDATE_GRAMMAR_GOLDENS") == "1":
        golden.write_bytes(actual_bytes)
        pytest.fail(
            f"Updated golden {golden.name}; re-run pytest WITHOUT "
            "CCE_UPDATE_GRAMMAR_GOLDENS to confirm green."
        )

    actual = json.loads(actual_bytes)
    expected = json.loads(golden_bytes)
    pytest.fail(
        "Grammar spans drifted from frozen golden.\n"
        f"  fixture:    {source.relative_to(REPO_ROOT)}\n"
        f"  golden:     {golden.relative_to(REPO_ROOT)}\n"
        f"  actual #spans:   {len(actual['spans'])}\n"
        f"  expected #spans: {len(expected['spans'])}\n"
        "Run `uv run python scripts/regenerate_grammar_spans.py` to update "
        "(intentional grammar bump) or investigate the tree-sitter regression."
    )
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `uv run pytest tests/test_grammar_stability.py -v`

Expected: `2 passed` (one parametrized case per language).

- [ ] **Step 3: Negative-control — perturb a fixture, confirm the test FAILS**

Run:

```bash
echo "// drift" >> tests/fixtures/simple_typescript/src/example.ts
uv run pytest tests/test_grammar_stability.py::test_grammar_spans_match_golden -v
```

Expected: the `typescript` parametrized case **FAILS** with the "Grammar spans drifted from frozen golden" message. Then revert:

```bash
git checkout -- tests/fixtures/simple_typescript/src/example.ts
uv run pytest tests/test_grammar_stability.py -q
```

Expected (after revert): `2 passed`.

- [ ] **Step 4: Smoke-test the opt-in regenerate path**

Run:

```bash
echo "// drift" >> tests/fixtures/simple_typescript/src/example.ts
CCE_UPDATE_GRAMMAR_GOLDENS=1 uv run pytest tests/test_grammar_stability.py -v || true
uv run pytest tests/test_grammar_stability.py -q
git checkout -- tests/fixtures/
```

Expected: first run fails with "Updated golden ..."; second run passes; final `git checkout` restores fixture + golden.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: `16 passed` (14 from Task 1's end-state + 2 new parametrized grammar-stability cases).

- [ ] **Step 6: Commit**

```bash
git add tests/test_grammar_stability.py
git commit -m "test: add tree-sitter grammar-stability gate (PREQ-A-4)"
```

---

## Task 6: Documentation Touch-Up

**Why:** Close the loop in `DEFERRED.md` and the POC PRD checklist so the next reader sees these items as done.

**Files:**
- Modify: `DEFERRED.md`

- [ ] **Step 1: Update `DEFERRED.md`**

Open `DEFERRED.md`. Find the entries (or section) referencing `PREQ-A-4`, `PREQ-D-2`, `PREQ-D-3`. For each:
- If listed as deferred -> move them to a "Done" section (or remove from "Deferred").
- Add a one-line note: `PREQ-A-4: closed by tests/test_grammar_stability.py + tests/fixtures/grammar_spans/`.
- Add a one-line note: `PREQ-D-2, PREQ-D-3: closed by tests/test_cli.py::test_sidecar_files_have_canonical_contents (implementation already in src/cce/cli.py::_write_outputs).`

If `DEFERRED.md` does not list these PREQ-* IDs at all, append a short "Closed since last revision" section with the same three lines.

- [ ] **Step 2: Commit**

```bash
git add DEFERRED.md
git commit -m "docs: mark PREQ-A-4 + PREQ-D-2 + PREQ-D-3 as closed"
```

---

## Final Verification

- [ ] **Run the full suite one last time**

Run: `uv run pytest -q`

Expected: `16 passed` in <1s.

- [ ] **Run the determinism gate**

Run: `uv run pytest tests/determinism_100x.py -q`

Expected: `1 passed`.

- [ ] **Self-score the repo (smoke)**

Run:

```bash
uv run cce score --spec ./scoring-spec.yaml --repo . --mode repo --out /tmp/cce-quick-wins --verify-digests false
ls /tmp/cce-quick-wins/
```

Expected: exit 0; prints `sha256:...`; directory contains `<hash>.json`, `<hash>.raw.json`, `<hash>.sha256`.

---

## Self-Review Notes

- **Spec coverage:** PREQ-D-2 (raw.json), PREQ-D-3 (sha256 sidecar), PREQ-A-4 (grammar-stability) each have a dedicated task and assertion. POC-GATE-7 is the CI gate that PREQ-A-4 unlocks; it runs automatically under the existing `uv run pytest -q` step in `.github/workflows/poc-determinism.yml`, so no workflow edit is needed.
- **Determinism risks for PREQ-A-4:** named-node walk is grammar-version-stable; we pin `tree-sitter==0.24.0` and `tree-sitter-language-pack==0.7.2` in `pyproject.toml`. If those versions are ever bumped, Task 5 will fail loudly and `scripts/regenerate_grammar_spans.py` is the documented escape hatch.
- **Why not also add a network-isolation / submodule-trap test here?** Those belong to POC-M-4 (container hardening) — out of scope for these quick wins. Tracked separately.
- **No production code changes** are required by this plan. Task 1 may surface a `_write_outputs` defect; if so, the fix is a small in-place edit and is explicitly authorised by Task 1 Step 2.
