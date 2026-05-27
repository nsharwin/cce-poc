# POC-M-5 Matrix CI + Golden Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close `POC-M-5` from `docs/poc-prd.md` §8 — *"determinism-100x test + GitHub Actions matrix CI (linux-x86_64, linux-arm64, macos-arm64). Golden corpus (3 fixtures) frozen."* — by shipping the artifacts that satisfy `POC-GATE-1`, `POC-GATE-2`, `PREQ-S-6` (strengthened), `PREQ-S-7`, and partially advance `POC-GATE-8` / `PNFR-PERF-1` (100k LoC fixture lands; perf timing logged; hard sign-off deferred to POC-M-7 nightly evidence). The grammar-stability gate (`POC-GATE-7`) already closed in PREQ-D, and Firecracker (`PREQ-X-4`), OTel exporter (`PREQ-O-1`), 7-day nightly (`POC-GATE-3`), external reviewer (`POC-GATE-4`), and the real `lizard`/`scc` analyzer wiring (`PREQ-A-1` finish) stay explicitly out of scope for this plan.

**Architecture:**
1. **Golden corpus = 3 fixtures, each with a frozen per-fixture `expected_record_hash.txt`:**
   - `tests/fixtures/simple_python/` — already exists (~6 LoC); add `expected_record_hash.txt` only.
   - `tests/fixtures/simple_typescript/` — skeleton exists (one `src/example.ts`); flesh out to ~50 LoC across 2 files so the TS analyzer actually contributes spans, then freeze its `expected_record_hash.txt`.
   - `tests/fixtures/large_synth_100k/` — NEW. Generated once by `scripts/gen_large_fixture.py` (deterministic seed → ~100k LoC across `python/` + `typescript/` subdirs) and committed as source files (NOT regenerated each CI run, so the on-disk SHA is stable).
2. **Per-fixture goldens are committed at `tests/fixtures/<name>/expected_record_hash.txt`** (single line: `sha256:<hex>\n`). A new `tests/test_golden_corpus.py` parametrises over the 3 fixtures, scores each one through the real `cce score` pipeline (via the same deterministic `git init` helper pattern used in `tests/test_submodule_trap.py`), and asserts `record_hash == cat expected_record_hash.txt`. Regeneration is gated by `CCE_UPDATE_RECORD_HASH_GOLDENS=1`, mirroring the `CCE_UPDATE_GRAMMAR_GOLDENS=1` pattern from `PREQ-A-4`.
3. **Strengthen `tests/determinism_100x.py` (`POC-GATE-1`)** with a second test, `test_determinism_100x_on_real_fixture`, that scores `simple_python` 100 times via the deterministic git-init helper and asserts the resulting `record_hash` set has cardinality 1. The new test is gated by `@pytest.mark.slow` so the existing synthetic test stays the fast default. Today `POC-GATE-1` is only proven on synthetic metrics (`tests/sample_data.py`); this closes the gap.
4. **Matrix CI (`POC-GATE-2`, `PREQ-S-7`):** extend the existing `deterministic-core` job in `.github/workflows/poc-determinism.yml` to **loop over all 3 fixtures** rather than score just `simple_python`. Each `(runner, fixture)` pair uploads one artifact named `record-hash-<runner>-<fixture>.txt`; before upload, a per-runner step asserts the hash matches `tests/fixtures/<fixture>/expected_record_hash.txt`. The downstream `compare-hashes` job then groups artifacts by fixture and asserts each group collapses to its committed golden — distinguishing "platform drift" (group disagreement) from "analyzer drift" (group agrees but disagrees with the golden).
5. **`POC-GATE-8` partial + `PNFR-PERF-1` soft gate:** add a `--max-seconds 300` wall-clock log to the `large_synth_100k` CI step. In POC-M-5 the assertion is **log-only** (warns and uploads a `perf-warning-<runner>.txt` artifact); POC-M-7 flips it to hard-fail after a week of nightly evidence.
6. **Negative controls:** every gate-closing task includes a negative-control step — mutate a fixture file (or the golden) and assert the test fails — so we are not silently green.

**Tech Stack:** Python 3.12, uv 0.9.27, pytest 9.0.3 (with new `slow` marker registered in `pyproject.toml`), `rfc8785==0.1.4`, GitHub Actions matrix (`ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-15`). No new runtime dependencies. The 100k LoC generator uses only the Python standard library (deterministic `random.Random(seed)` + `sorted(...)` iteration; no `set` ordering reliance).

---

## File Structure

**Creates:**
- `scripts/gen_large_fixture.py` — deterministic generator for `tests/fixtures/large_synth_100k/`. Reproducible across Python 3.12 minor versions (sorts all iteration, uses an explicit `random.Random(seed=0xCCE5)`).
- `tests/fixtures/large_synth_100k/` — committed generator output, structured as `python/<modN>.py` + `typescript/<modN>.ts` summing to ~100k LoC total; plus `README.md` documenting the regen command and `expected_record_hash.txt`.
- `tests/fixtures/large_synth_100k/expected_record_hash.txt`
- `tests/fixtures/simple_python/expected_record_hash.txt`
- `tests/fixtures/simple_typescript/expected_record_hash.txt`
- `tests/fixtures/simple_typescript/src/<additional .ts files>` — flesh out the skeleton to ~50 LoC across 2 files so the TS analyzer emits non-trivial spans.
- `tests/test_golden_corpus.py` — parametrised over the 3 fixtures; honours `CCE_UPDATE_RECORD_HASH_GOLDENS=1` to regenerate the committed goldens.

**Modifies:**
- `tests/determinism_100x.py` — add `test_determinism_100x_on_real_fixture` gated by `@pytest.mark.slow`; keep the existing synthetic test as the fast path.
- `.github/workflows/poc-determinism.yml` — per-fixture loop inside `deterministic-core`; new per-fixture golden-comparison step; extended artifact naming `record-hash-<runner>-<fixture>.txt`; `compare-hashes` job groups by fixture and asserts each group equals its committed golden; `--max-seconds 300` perf-timing log on `large_synth_100k`.
- `pyproject.toml` — register the `slow` pytest marker under `[tool.pytest.ini_options].markers`.
- `DEFERRED.md` — flip `PREQ-S-7` and `POC-GATE-1` / `POC-GATE-2` to ✅ Closed with one-line citations; tighten the `POC-GATE-8` entry to "100k LoC fixture landed; perf timing logged; hard gate pending nightly evidence (POC-M-7)".
- `README.md` — add a "Golden corpus & regenerating record hashes" section citing `CCE_UPDATE_RECORD_HASH_GOLDENS=1`.

**Does NOT touch:**
- `src/cce/scoring.py`, `src/cce/canonical.py`, `src/cce/spec.py`, `src/cce/analyzer.py`, `src/cce/git_ops.py`, `src/cce/runtime.py`, `src/cce/cli.py` — POC-M-5 is purely about test/CI/fixture infrastructure. Scoring math, canonicalisation, sidecar contract, and the analyzer surface are frozen.
- `Dockerfile`, `scoring-spec.yaml` — locked by POC-M-4.

---

## Task 1: `PREQ-S-7` + `POC-GATE-2` — Expand `simple_typescript` Fixture and Freeze its Golden

**Why:** `PREQ-S-7` requires "`record_hash` is identical on Linux x86_64, Linux arm64, macOS arm64 for the golden corpus." The current `simple_typescript` fixture is a one-file skeleton — barely exercises the TS analyzer. Until the fixture has meaningful TS spans, the resulting `record_hash` is uninteresting and the cross-platform assertion is weak. This task also commits the **per-fixture** golden file that the rest of the plan depends on.

**Files:**
- Modify: `tests/fixtures/simple_typescript/src/example.ts` (current skeleton — keep but extend).
- Create: `tests/fixtures/simple_typescript/src/<one or two additional .ts files>`, `tests/fixtures/simple_typescript/expected_record_hash.txt`, `tests/fixtures/simple_python/expected_record_hash.txt`.

- [ ] **Step 1: Audit current TS fixture content**

Run:

```bash
ls tests/fixtures/simple_typescript/src/
wc -l tests/fixtures/simple_typescript/src/*.ts
```

Expected: one file `example.ts`, < 20 LoC. Record the current LoC so the post-edit diff is auditable.

- [ ] **Step 2: Flesh out the TS fixture to ~50 LoC across 2 files**

Add a second TS file, e.g. `tests/fixtures/simple_typescript/src/utils.ts`, with one exported class (3–4 methods, simple control flow) and one free function. Extend `example.ts` to import `utils.ts` and call into it. Aim for ~50 LoC total — large enough to produce non-trivial `lizard`/tree-sitter span output, small enough to read in a glance.

Constraints:
- Use plain TypeScript (no decorators, no JSX, no `import type`-only edges).
- No external imports (no `node_modules`); everything resolves within the fixture.
- ASCII only — no smart quotes, no NBSPs — so the file SHA is stable across editors.

Verify the fixture parses with the existing TS analyzer:

```bash
uv run cce score \
  --spec ./scoring-spec.yaml \
  --repo ./tests/fixtures/simple_typescript \
  --mode repo \
  --out /tmp/cce-ts-smoke \
  --verify-digests false
```

Expected: exit 0; `/tmp/cce-ts-smoke/record_hash.txt` exists and starts with `sha256:`.

- [ ] **Step 3: Capture initial golden hashes (Python and TypeScript)**

For each of `simple_python` and `simple_typescript`, capture the `record_hash` produced by the current analyzer pipeline into a per-fixture golden file:

```bash
for fx in simple_python simple_typescript; do
  out=$(mktemp -d)
  uv run cce score \
    --spec ./scoring-spec.yaml \
    --repo "./tests/fixtures/${fx}" \
    --mode repo \
    --out "${out}" \
    --verify-digests false
  cp "${out}/record_hash.txt" "tests/fixtures/${fx}/expected_record_hash.txt"
done
```

Verify:

```bash
cat tests/fixtures/simple_python/expected_record_hash.txt
cat tests/fixtures/simple_typescript/expected_record_hash.txt
```

Expected: each file is a single line `sha256:<64-hex>\n`. Commit both.

> ⚠️ **Capture under the current analyzer surface only.** Per Self-Review Note 2, the eventual `PREQ-A-1` finish (real `lizard`/`scc` + tree-sitter Python) will deliberately invalidate these goldens; that future plan owns the regen step. POC-M-5 freezes today's behaviour as the cross-platform reproducibility floor.

- [ ] **Step 4: Negative-control — mutate the fixture and confirm the hash changes**

Append a trailing comment to the TS fixture, rescore, and assert the new hash differs from the committed golden:

```bash
echo "// nonce-$(date +%s)" >> tests/fixtures/simple_typescript/src/example.ts
out=$(mktemp -d)
uv run cce score \
  --spec ./scoring-spec.yaml \
  --repo ./tests/fixtures/simple_typescript \
  --mode repo \
  --out "${out}" \
  --verify-digests false
test "$(cat ${out}/record_hash.txt)" != "$(cat tests/fixtures/simple_typescript/expected_record_hash.txt)" \
  && echo "negative-control OK" \
  || (echo "FAIL: mutated fixture produced same hash as golden" && exit 1)
git checkout -- tests/fixtures/simple_typescript/src/example.ts
```

Expected: prints `negative-control OK`. Then verify the fixture is restored: `git status tests/fixtures/simple_typescript/` shows no diff.

---

## Task 2: `POC-GATE-8` partial + `PNFR-PERF-1` — `large_synth_100k` Fixture Generator and Committed Sources

**Why:** `POC-GATE-8` requires "`PNFR-PERF-1` met on 100k LoC fixture" (≤ 5 minutes wall time on M2 Pro / equivalent x86_64). The fixture does not exist yet. This task introduces a **deterministic** generator and commits its output so the fixture sources have a stable on-disk SHA — CI never regenerates them, only scores them. The perf assertion itself is soft (log-only) in POC-M-5 and gets a hard gate in POC-M-7.

**Files:**
- Create: `scripts/gen_large_fixture.py`, `tests/fixtures/large_synth_100k/README.md`, `tests/fixtures/large_synth_100k/python/<modN>.py`, `tests/fixtures/large_synth_100k/typescript/<modN>.ts` (committed generator output), `tests/fixtures/large_synth_100k/expected_record_hash.txt`.

- [ ] **Step 1: Write `scripts/gen_large_fixture.py`**

Constraints the generator MUST satisfy (encoded as docstring + asserts inside the script):

- Single CLI: `python scripts/gen_large_fixture.py --out tests/fixtures/large_synth_100k --seed 0xCCE5 --target-loc 100000`.
- Determinism: use exactly one `random.Random(args.seed)` instance; never call the module-level `random.*` API. Sort every iterable before iterating (`sorted(names)`, `sorted(os.listdir(...))`). Do NOT iterate over `set` or `dict.keys()` without sorting.
- File layout: `python/mod_NNNN.py` and `typescript/mod_NNNN.ts` with `NNNN` zero-padded to 4 digits. Aim for ~500 modules × ~100 LoC each → ~100k LoC total split roughly 50/50 between Python and TS.
- Per-module content: each module exports 3–5 functions with predictable bodies (chained `if`/`for`, integer arithmetic, no I/O, no external imports). Function names and parameter names are derived from the seeded RNG so the content is non-trivial but reproducible.
- Output is byte-identical across re-runs with the same seed and across Python 3.12 minor versions. The script must end by printing a final-pass digest:
  `sha256(b"".join(sorted(<rel_path>.encode() + b"\0" + open(p, "rb").read() for p in walk(out))))`
  and assert it matches a constant baked into the script — if a future Python version perturbs file ordering or formatting, the assertion catches it.
- No network calls. No template engines (use plain string formatting).

- [ ] **Step 2: Generate and commit the fixture tree**

Run:

```bash
mkdir -p tests/fixtures/large_synth_100k
python scripts/gen_large_fixture.py \
  --out tests/fixtures/large_synth_100k \
  --seed 0xCCE5 \
  --target-loc 100000
wc -l tests/fixtures/large_synth_100k/python/*.py tests/fixtures/large_synth_100k/typescript/*.ts | tail -1
```

Expected: total LoC reported by `wc -l` between 95_000 and 105_000. Commit all generated files under `tests/fixtures/large_synth_100k/`.

- [ ] **Step 3: Write `tests/fixtures/large_synth_100k/README.md`**

Document:

- What the fixture is (synthetic 100k LoC, half Python / half TS).
- The exact regeneration command (Step 2 above) — emphasise the `--seed 0xCCE5` is part of the contract.
- The PRD IDs it satisfies: `POC-GATE-8` (partial, perf-timing only in POC-M-5) and `PNFR-PERF-1` (soft gate).
- A "do not edit by hand" warning — edits invalidate `expected_record_hash.txt` silently.

- [ ] **Step 4: Capture the 100k golden hash**

```bash
out=$(mktemp -d)
uv run cce score \
  --spec ./scoring-spec.yaml \
  --repo ./tests/fixtures/large_synth_100k \
  --mode repo \
  --out "${out}" \
  --verify-digests false
cp "${out}/record_hash.txt" tests/fixtures/large_synth_100k/expected_record_hash.txt
cat tests/fixtures/large_synth_100k/expected_record_hash.txt
```

Expected: single-line `sha256:<64-hex>\n`; commit the file.

- [ ] **Step 5: Negative-control — regen with a different seed and confirm the hash changes**

```bash
tmpdir=$(mktemp -d)
python scripts/gen_large_fixture.py --out "${tmpdir}" --seed 0xDEAD --target-loc 100000
out=$(mktemp -d)
uv run cce score --spec ./scoring-spec.yaml --repo "${tmpdir}" --mode repo --out "${out}" --verify-digests false
test "$(cat ${out}/record_hash.txt)" != "$(cat tests/fixtures/large_synth_100k/expected_record_hash.txt)" \
  && echo "negative-control OK" \
  || (echo "FAIL: different seed produced same hash" && exit 1)
```

Expected: prints `negative-control OK`. The original committed fixture is untouched (Step 5 wrote to `${tmpdir}`, not to the repo).

- [ ] **Step 6: Re-run the generator over the committed location and confirm idempotence**

```bash
rm -rf /tmp/regen && cp -R tests/fixtures/large_synth_100k /tmp/regen
python scripts/gen_large_fixture.py --out /tmp/regen --seed 0xCCE5 --target-loc 100000
diff -r tests/fixtures/large_synth_100k /tmp/regen && echo "idempotence OK"
```

Expected: prints `idempotence OK`; `diff` produces no output. Catches accidental non-determinism in the generator (e.g., iterating an unsorted `set`).

---

## Task 3: `PREQ-S-7` — Golden-Comparison Test and `CCE_UPDATE_RECORD_HASH_GOLDENS` Regen Path

**Why:** `PREQ-S-7` requires identical `record_hash` per fixture across all three OS targets, anchored to a **committed** golden — not just cross-runner agreement. Today the CI workflow only checks that the three runners agree on `simple_python`; there is no per-fixture frozen golden in the repo, so analyzer drift across the whole matrix would silently produce a new (still consistent) hash. This task closes that loop with a local test that asserts each fixture matches its committed `expected_record_hash.txt`, plus a documented regen path that mirrors the `PREQ-A-4` grammar-spans pattern.

**Files:**
- Create: `tests/test_golden_corpus.py`.

- [ ] **Step 1: Write `tests/test_golden_corpus.py`**

Structure (mirrors `tests/test_submodule_trap.py`):

```python
"""PREQ-S-7: per-fixture record_hash matches its committed golden.

Each fixture under tests/fixtures/ that ships an ``expected_record_hash.txt``
is scored end-to-end via the real ``cce score`` pipeline, and the resulting
hash is asserted to equal the committed golden.

Regen path:
    CCE_UPDATE_RECORD_HASH_GOLDENS=1 uv run pytest tests/test_golden_corpus.py
(mirrors CCE_UPDATE_GRAMMAR_GOLDENS=1 from PREQ-A-4.)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

GOLDEN_FIXTURES = sorted(
    p.parent.name
    for p in FIXTURES_DIR.glob("*/expected_record_hash.txt")
)


def _score_fixture(fixture: str, work: Path) -> str:
    # Copy + deterministic git init (mirrors tests/test_submodule_trap.py).
    shutil.copytree(FIXTURES_DIR / fixture, work, dirs_exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CCE Test",
        "GIT_AUTHOR_EMAIL": "cce@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "CCE Test",
        "GIT_COMMITTER_EMAIL": "cce@example.test",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=work, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=work, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "golden"], cwd=work, check=True, env=env)

    out = work.parent / "out"
    proc = subprocess.run(
        [
            sys.executable, "-m", "cce", "score",
            "--spec", str(REPO_ROOT / "scoring-spec.yaml"),
            "--repo", str(work),
            "--mode", "repo",
            "--out", str(out),
            "--verify-digests", "false",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    return (out / "record_hash.txt").read_text().strip()


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES)
def test_record_hash_matches_golden(fixture: str, tmp_path: Path) -> None:
    actual = _score_fixture(fixture, tmp_path / "repo")
    golden_path = FIXTURES_DIR / fixture / "expected_record_hash.txt"

    if os.environ.get("CCE_UPDATE_RECORD_HASH_GOLDENS") == "1":
        golden_path.write_text(actual + "\n")
        pytest.skip(f"updated golden for {fixture}")

    expected = golden_path.read_text().strip()
    assert actual == expected, (
        f"record_hash drift for fixture {fixture!r}:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        f"If this is intentional, regenerate with "
        f"CCE_UPDATE_RECORD_HASH_GOLDENS=1 uv run pytest tests/test_golden_corpus.py"
    )
```

Notes:
- Parametrisation discovers fixtures by file presence — no hard-coded list. Adding a fixture is "drop a folder with `expected_record_hash.txt`".
- The deterministic git-init env-var block is identical to `tests/test_submodule_trap.py`. Keep it byte-for-byte so future maintainers recognise the pattern.

- [ ] **Step 2: Run the test and confirm all 3 fixtures pass**

```bash
uv run pytest tests/test_golden_corpus.py -v
```

Expected: 3 parametrised cases, all PASSED (`large_synth_100k` may take ~10s locally; that is fine — the slow CI variant is covered by Task 4 / 5).

- [ ] **Step 3: Negative-control — mutate the golden and confirm the test fails**

```bash
golden=tests/fixtures/simple_python/expected_record_hash.txt
orig=$(cat "$golden")
echo "sha256:0000000000000000000000000000000000000000000000000000000000000000" > "$golden"
uv run pytest tests/test_golden_corpus.py::test_record_hash_matches_golden[simple_python] \
  && (echo "FAIL: stale golden was accepted" && exit 1) \
  || echo "negative-control OK"
echo "$orig" > "$golden"   # restore
```

Expected: the parametrised case for `simple_python` FAILS with a clear "record_hash drift" message; we restore the original golden before continuing.

- [ ] **Step 4: Exercise the regen path**

Pretend the analyzer has changed (without actually changing it): delete one of the goldens and regenerate via the env var:

```bash
rm tests/fixtures/simple_python/expected_record_hash.txt
CCE_UPDATE_RECORD_HASH_GOLDENS=1 uv run pytest tests/test_golden_corpus.py::test_record_hash_matches_golden[simple_python]
cat tests/fixtures/simple_python/expected_record_hash.txt
```

Expected: the test SKIPS with reason "updated golden for simple_python"; the deleted file is recreated with the current hash. Confirm via `git diff tests/fixtures/simple_python/expected_record_hash.txt` that the regen produced the same content as before (i.e., the analyzer has NOT drifted).

---

## Task 4: `POC-GATE-1` — Strengthen `tests/determinism_100x.py` with a Real-Fixture Loop

**Why:** `POC-GATE-1` reads "`pytest tests/determinism_100x.py` green." Today the test only proves determinism of the **scoring core** on **synthetic raw metrics** from `tests/sample_data.py` — it never invokes the real analyzer, never touches a fixture, and therefore would not catch a non-deterministic bug in `analyzer.py`, `git_ops.py`, or any tree-sitter call path. This task closes the gap by adding a second test that runs the **full pipeline** 100×, while keeping the existing synthetic test as the fast default (so local dev runs don't slow down).

**Files:**
- Modify: `tests/determinism_100x.py`, `pyproject.toml`.

- [ ] **Step 1: Register the `slow` pytest marker in `pyproject.toml`**

Add (or extend) the markers section:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: tests that take more than ~1s to run (opt-in via -m slow)",
]
```

Verify the marker is recognised (no warning):

```bash
uv run pytest --collect-only tests/determinism_100x.py 2>&1 | grep -i "unknown" || echo "marker registered OK"
```

Expected: prints `marker registered OK`.

- [ ] **Step 2: Add `test_determinism_100x_on_real_fixture` to `tests/determinism_100x.py`**

Append a second test that scores `tests/fixtures/simple_python` 100 times via the same deterministic git-init helper used in `tests/test_submodule_trap.py` and `tests/test_golden_corpus.py`. Sketch:

```python
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "simple_python"


def _score_once(work_root: Path, run_idx: int) -> str:
    work = work_root / f"run_{run_idx:03d}"
    shutil.copytree(FIXTURE, work)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CCE Test",
        "GIT_AUTHOR_EMAIL": "cce@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "CCE Test",
        "GIT_COMMITTER_EMAIL": "cce@example.test",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=work, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=work, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "fx"], cwd=work, check=True, env=env)
    out = work.parent / f"out_{run_idx:03d}"
    subprocess.run(
        [
            sys.executable, "-m", "cce", "score",
            "--spec", str(REPO_ROOT / "scoring-spec.yaml"),
            "--repo", str(work),
            "--mode", "repo",
            "--out", str(out),
            "--verify-digests", "false",
        ],
        check=True,
        env={**env, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    return (out / "record_hash.txt").read_text().strip()


@pytest.mark.slow
def test_determinism_100x_on_real_fixture(tmp_path: Path) -> None:
    hashes = {_score_once(tmp_path, i) for i in range(100)}
    assert len(hashes) == 1, f"non-deterministic: {len(hashes)} unique hashes across 100 runs"
```

Keep the existing `test_determinism_100x_produces_one_unique_record_hash` UNTOUCHED — it stays the fast default. The new test is opt-in via `-m slow`.

- [ ] **Step 3: Run the slow gate locally**

```bash
uv run pytest -m slow tests/determinism_100x.py -v
```

Expected: `test_determinism_100x_on_real_fixture` PASSES. Note the elapsed time (target: under ~60s on a laptop — if it exceeds 5 min, reduce the loop to a smaller fixture or document the budget in the test docstring).

Also confirm the fast path is unchanged:

```bash
uv run pytest tests/determinism_100x.py -v
```

Expected: only the original synthetic test runs (the `slow`-marked test is deselected by default); 1 passed in < 1s.

- [ ] **Step 4: Negative-control — inject a non-deterministic input and confirm the test fails**

Temporarily patch the test to thread a varying `computed_at` into the **`cce score`** invocation by setting `SOURCE_DATE_EPOCH` differently per iteration. Concretely, edit `_score_once` to add `env["SOURCE_DATE_EPOCH"] = str(1_700_000_000 + run_idx)` before subprocess.run. (Only do this transiently; revert after.)

If the scoring core correctly ignores `SOURCE_DATE_EPOCH` (it should — `computed_at` is excluded from the canonical metrics payload per `docs/poc-prd.md` §5.1), the test should STILL pass. That confirms the gate distinguishes "input churn we don't care about" from "real drift". Then, as a stronger negative control, edit the fixture inside the per-iteration tmpdir on a single iteration:

```python
if run_idx == 7:
    (work / "pkg" / "example.py").write_text("# drift\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=work, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "--amend", "--no-edit"], cwd=work, check=True, env=env)
```

Expected: with this in place, the test FAILS with `non-deterministic: 2 unique hashes across 100 runs`. Revert the edit and confirm the test PASSES again. Do NOT commit the negative-control mutation.

---

## Task 5: `POC-GATE-2` + `PREQ-S-7` + `POC-GATE-8` (partial) — Wire 3 Fixtures into Matrix CI

**Why:** Today `.github/workflows/poc-determinism.yml::deterministic-core` only scores `simple_python` and only asserts cross-runner agreement; `compare-hashes` has no per-fixture grouping and no per-fixture golden comparison. This task extends the matrix to all three fixtures, switches the artifact-naming scheme to `record-hash-<runner>-<fixture>.txt`, asserts each `(runner, fixture)` pair matches its committed golden BEFORE upload, regroups the downstream comparison job by fixture, and adds a soft `--max-seconds 300` perf-timing log on the `large_synth_100k` fixture for `POC-GATE-8` partial / `PNFR-PERF-1`.

**Files:**
- Modify: `.github/workflows/poc-determinism.yml`.

- [ ] **Step 1: Extend the `deterministic-core` job to loop over all 3 fixtures**

Inside the existing `deterministic-core` job, replace the single `simple_python`-specific score step with a per-fixture loop. The structure (after the existing checkout / uv-setup / digest-bypass steps):

```yaml
      - name: Score golden corpus
        id: score
        env:
          GIT_AUTHOR_NAME: CCE Test
          GIT_AUTHOR_EMAIL: cce@example.test
          GIT_AUTHOR_DATE: "2026-01-01T00:00:00+0000"
          GIT_COMMITTER_NAME: CCE Test
          GIT_COMMITTER_EMAIL: cce@example.test
          GIT_COMMITTER_DATE: "2026-01-01T00:00:00+0000"
        run: |
          set -euo pipefail
          mkdir -p cce-out
          for fx in simple_python simple_typescript large_synth_100k; do
            work="$(mktemp -d)"
            cp -R "tests/fixtures/${fx}/." "${work}/"
            (
              cd "${work}"
              git init -q --initial-branch=main
              git add .
              git commit -q -m "fx-${fx}"
            )
            out="cce-out/${fx}"
            mkdir -p "${out}"
            # PNFR-PERF-1 soft gate: capture wall-time for large_synth_100k.
            start=$(date +%s)
            uv run cce score \
              --spec ./scoring-spec.yaml \
              --repo "${work}" \
              --mode repo \
              --out "${out}" \
              --verify-digests false
            elapsed=$(( $(date +%s) - start ))
            echo "fixture=${fx} elapsed_sec=${elapsed}" | tee -a cce-out/perf.log
            if [ "${fx}" = "large_synth_100k" ] && [ "${elapsed}" -gt 300 ]; then
              echo "::warning::PNFR-PERF-1 soft gate exceeded: ${fx} took ${elapsed}s (>300s)"
              echo "${fx} ${elapsed}s" >> cce-out/perf-warning.txt
            fi
            # PREQ-S-7: per-runner golden comparison BEFORE upload.
            expected=$(cat "tests/fixtures/${fx}/expected_record_hash.txt")
            actual=$(cat "${out}/record_hash.txt")
            if [ "${expected}" != "${actual}" ]; then
              echo "::error::record_hash drift on ${{ matrix.name }} for ${fx}: expected=${expected} actual=${actual}"
              exit 1
            fi
            # Rename for artifact upload: record-hash-<runner>-<fixture>.txt
            cp "${out}/record_hash.txt" "cce-out/record-hash-${{ matrix.name }}-${fx}.txt"
          done
```

Replace the existing single `actions/upload-artifact` step with one that uploads all per-fixture hash files (and the optional perf-warning artifact):

```yaml
      - name: Upload per-fixture record hashes
        uses: actions/upload-artifact@<pinned-sha>
        with:
          name: record-hashes-${{ matrix.name }}
          path: |
            cce-out/record-hash-${{ matrix.name }}-*.txt
            cce-out/perf-warning.txt
          if-no-files-found: warn
```

(Keep the existing SHA-pinned `actions/upload-artifact` version — do not bump it as part of this task.)

- [ ] **Step 2: Rewrite `compare-hashes` to group by fixture and assert each group equals its committed golden**

Replace the existing single-fixture comparison logic with a per-fixture grouping pass. Sketch:

```yaml
  compare-hashes:
    name: compare-hashes
    needs: [deterministic-core, container-isolation]
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@<pinned-sha>
      - uses: actions/download-artifact@<pinned-sha>
        with:
          path: artifacts
      - name: Group + compare per fixture
        run: |
          set -euo pipefail
          fail=0
          for fx in simple_python simple_typescript large_synth_100k; do
            mapfile -t files < <(find artifacts -name "record-hash-*-${fx}.txt" | sort)
            if [ "${#files[@]}" -eq 0 ]; then
              echo "::error::no artifacts found for fixture ${fx}"
              fail=1
              continue
            fi
            # Unique-hash count across runners for this fixture.
            unique=$(cat "${files[@]}" | sort -u | wc -l | tr -d ' ')
            golden=$(cat "tests/fixtures/${fx}/expected_record_hash.txt")
            agreed=$(cat "${files[0]}")
            echo "fixture=${fx} files=${#files[@]} unique=${unique} golden=${golden} agreed=${agreed}"
            if [ "${unique}" -ne 1 ]; then
              echo "::error::platform drift: ${fx} has ${unique} unique hashes across runners"
              for f in "${files[@]}"; do echo "  $(basename "${f}"): $(cat "${f}")"; done
              fail=1
            elif [ "${agreed}" != "${golden}" ]; then
              echo "::error::analyzer drift: ${fx} agrees across runners but differs from committed golden"
              fail=1
            fi
          done
          exit "${fail}"
```

This intentionally separates **platform drift** (unique > 1 — different runners disagree) from **analyzer drift** (unique = 1 but the value moved). Both fail the job; the error message tells the reviewer which class to investigate.

- [ ] **Step 3: Add `container-isolation` to `compare-hashes.needs` if not already there**

(Already added in POC-M-4 — confirm by inspection. If absent, add it so a passing container run blocks the compare step.)

- [ ] **Step 4: Local CI dry-run via `act` (optional but recommended)**

```bash
# Requires `act` (https://github.com/nektos/act). Linux-only step.
act -j deterministic-core -P ubuntu-24.04=catthehacker/ubuntu:act-24.04 2>&1 | tail -40
```

Expected: the `Score golden corpus` step runs the loop 3× and the `Upload per-fixture record hashes` step succeeds. If `act` is unavailable, skip this step — Step 5 (real CI smoke) is the authoritative check.

- [ ] **Step 5: Push to a draft PR and confirm CI is green on the canonical case**

Open a draft PR with all of Tasks 1–5 applied. Required outcome:

- `deterministic-core (linux-x86_64)`, `deterministic-core (linux-arm64)`, `deterministic-core (macos-arm64)` all green.
- `container-isolation (linux-x86_64)`, `container-isolation (linux-arm64)` all green (carried over from POC-M-4 — must not regress).
- `compare-hashes` green; the step log prints `fixture=<name> files=3 unique=1 golden=<sha256:…> agreed=<sha256:…>` for each fixture and exits 0.

- [ ] **Step 6: Negative-control — push a fixture mutation and assert CI red**

In a throwaway branch off the draft PR, mutate a fixture (e.g., `echo "// drift" >> tests/fixtures/simple_typescript/src/example.ts`) **without** updating its golden. Push.

Expected CI behaviour:
- All three `deterministic-core` runners fail at the per-runner golden-comparison step with `::error::record_hash drift on <runner> for simple_typescript: expected=… actual=…`.
- `compare-hashes` is skipped (its `needs` failed).

Confirm by reading the Actions log. Then revert the mutation and confirm CI returns to green. Do NOT merge the negative-control commit.

- [ ] **Step 7: Negative-control — push a runner-specific drift simulation**

In a separate throwaway branch, prefix the `Score golden corpus` step with a runner-specific perturbation, e.g.:

```yaml
      - name: Simulate platform drift (DO NOT MERGE)
        if: matrix.name == 'macos-arm64'
        run: echo "// macos-only drift" >> tests/fixtures/simple_typescript/src/example.ts
```

Push. Expected:
- The `macos-arm64` `deterministic-core` matrix leg fails at the per-runner golden comparison.
- If the per-runner gate is somehow bypassed (e.g., a future refactor removes it), `compare-hashes` MUST still fail with `::error::platform drift: simple_typescript has 2 unique hashes across runners`.

This step confirms the dual-layer defence (per-runner golden + per-fixture grouping) is both wired in. Revert the branch when done.

---

## Task 6: DEFERRED.md Closure + README Touch-Up

**Why:** Per `docs/poc-prd.md` §13 rule 1, every closed PREQ/POC-GATE ID must be flipped in `DEFERRED.md` with a citation. POC-M-5 closes three IDs outright (`POC-GATE-1`, `POC-GATE-2`, `PREQ-S-7`) and tightens one (`POC-GATE-8`). The README needs a short paragraph on the new regen workflow so future contributors (and external reviewers from `POC-GATE-4`) know how to update goldens when the analyzer surface legitimately changes.

**Files:**
- Modify: `DEFERRED.md`, `README.md`.

- [ ] **Step 1: Flip `POC-GATE-1` to ✅ Closed in `DEFERRED.md`**

Replace the current `POC-GATE-1` entry with:

```markdown
### POC-GATE-1 ✅ Closed
Real-fixture determinism-100x gate added in `tests/determinism_100x.py::test_determinism_100x_on_real_fixture` (gated by `@pytest.mark.slow`). The existing synthetic test remains the fast default. POC-M-5 plan: `docs/plans/2026-05-24-poc-m-5-matrix-ci-and-golden-corpus.md` Task 4.
```

- [ ] **Step 2: Flip `POC-GATE-2` to ✅ Closed in `DEFERRED.md`**

```markdown
### POC-GATE-2 ✅ Closed
GitHub Actions matrix (`ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-15`) scores all 3 golden fixtures and asserts each runner's `record_hash` matches the committed golden BEFORE upload; the `compare-hashes` job groups artifacts by fixture and distinguishes platform drift from analyzer drift. See `.github/workflows/poc-determinism.yml::deterministic-core` and `compare-hashes`. POC-M-5 plan: Task 5.
```

- [ ] **Step 3: Flip `PREQ-S-7` to ✅ Closed in `DEFERRED.md`**

```markdown
### PREQ-S-7 ✅ Closed
Per-fixture golden `record_hash` files committed at `tests/fixtures/<name>/expected_record_hash.txt` for `simple_python`, `simple_typescript`, and `large_synth_100k`. Asserted both locally (`tests/test_golden_corpus.py`) and per-runner in CI. Regen path: `CCE_UPDATE_RECORD_HASH_GOLDENS=1 uv run pytest tests/test_golden_corpus.py`. POC-M-5 plan: Tasks 1–3.
```

- [ ] **Step 4: Tighten the `POC-GATE-8` entry in `DEFERRED.md`**

Replace the existing entry with:

```markdown
### POC-GATE-8 ⏳ Partial
100k LoC fixture (`tests/fixtures/large_synth_100k/`, generated by `scripts/gen_large_fixture.py --seed 0xCCE5`) landed in POC-M-5; CI logs end-to-end wall-time per runner and emits a `::warning` if `> 300s` (`PNFR-PERF-1` soft gate). Hard gate is deferred to POC-M-7 nightly evidence — flip to ✅ Closed once 7 consecutive nights stay under 300s on all three runners.
```

- [ ] **Step 5: Add a "Golden corpus & regenerating record hashes" section to `README.md`**

Append to `README.md` (after the existing "Running in the pinned container" section from POC-M-4):

```markdown
### Golden corpus & regenerating record hashes

The repository ships three golden fixtures used by both CI and the local determinism gate:

- `tests/fixtures/simple_python/` (tiny Python repo)
- `tests/fixtures/simple_typescript/` (tiny TypeScript repo)
- `tests/fixtures/large_synth_100k/` (~100k LoC, generated by `scripts/gen_large_fixture.py`; do NOT edit by hand)

Each fixture commits an `expected_record_hash.txt` file holding the SHA-256 `record_hash` produced by the current analyzer surface (per `scoring-spec.yaml`). `tests/test_golden_corpus.py` and CI both assert each fixture's score matches its golden.

If the analyzer surface legitimately changes (e.g., a `PREQ-A-1` analyzer rewrite), regenerate the goldens in one command:

```bash
CCE_UPDATE_RECORD_HASH_GOLDENS=1 uv run pytest tests/test_golden_corpus.py
```

Commit the resulting `expected_record_hash.txt` changes in the same PR as the analyzer change, with the `PREQ-*` ID quoted verbatim in the commit message per `docs/poc-prd.md` §13 rule 1.
```

- [ ] **Step 6: Confirm all six edits are present**

```bash
grep -nE "POC-GATE-1|POC-GATE-2|PREQ-S-7|POC-GATE-8" DEFERRED.md
grep -n "Golden corpus & regenerating record hashes" README.md
```

Expected: each of the four PRD IDs appears on the new "✅ Closed" / "⏳ Partial" lines; the README section heading is present exactly once.

---

## Final Verification

Run this checklist at the end of the implementation PR. Every command must succeed before requesting review.

- [ ] **Fast pytest suite:**
  ```bash
  uv run pytest -q
  ```
  Expected: all tests pass (POC-M-5 adds 3 new parametrised cases in `tests/test_golden_corpus.py` plus the unchanged synthetic test in `tests/determinism_100x.py`). The new `slow`-marked test is auto-deselected.

- [ ] **Slow determinism gate:**
  ```bash
  uv run pytest -m slow tests/determinism_100x.py -v
  ```
  Expected: `test_determinism_100x_on_real_fixture` passes; elapsed time under ~120s on a laptop.

- [ ] **Golden corpus gate (explicit):**
  ```bash
  uv run pytest tests/test_golden_corpus.py -v
  ```
  Expected: 3 parametrised cases pass.

- [ ] **Lint:**
  ```bash
  uv run ruff check .
  ```
  Expected: clean (no new issues introduced by this milestone; pre-existing E501 in `tests/test_grammar_stability.py` is untouched and not enforced by CI).

- [ ] **Generator idempotence:**
  ```bash
  cp -R tests/fixtures/large_synth_100k /tmp/regen
  python scripts/gen_large_fixture.py --out /tmp/regen --seed 0xCCE5 --target-loc 100000
  diff -r tests/fixtures/large_synth_100k /tmp/regen
  ```
  Expected: no diff.

- [ ] **CI matrix on a draft PR:**

  Open a draft PR and confirm all jobs land green:
  - `deterministic-core (linux-x86_64)` ✅
  - `deterministic-core (linux-arm64)` ✅
  - `deterministic-core (macos-arm64)` ✅
  - `container-isolation (linux-x86_64)` ✅ (regression check from POC-M-4)
  - `container-isolation (linux-arm64)` ✅ (regression check from POC-M-4)
  - `compare-hashes` ✅ — log prints `fixture=<name> files=3 unique=1 golden=<sha256:…> agreed=<sha256:…>` for each of the three fixtures.

- [ ] **PRD traceability:** every commit message in the PR quotes the closed/advanced PRD IDs (`POC-GATE-1`, `POC-GATE-2`, `PREQ-S-7`, `POC-GATE-8`, `PNFR-PERF-1`) verbatim, per `docs/poc-prd.md` §13 rule 1.

---

## Self-Review Notes

1. **Spec coverage.** The plan closes `POC-GATE-1` (real-fixture 100x), `POC-GATE-2` (matrix CI + per-fixture goldens), `PREQ-S-7` (committed per-fixture goldens + regen path), and partially advances `POC-GATE-8` / `PNFR-PERF-1` (100k fixture landed, perf logged, hard sign-off deferred). `POC-GATE-3` (7-day nightly), `POC-GATE-4` (external reviewer), `PREQ-O-1` (OTel), and the `PREQ-A-1` analyzer-rewrite all stay explicitly out of scope and get their own future plans per the recommended roadmap in `.junie/plans/draft-poc-m-4-writing-plan.md`.

2. **Golden fragility under future analyzer changes.** The committed `expected_record_hash.txt` files snapshot today's analyzer surface (`ast` for Python, tree-sitter for TS, no `lizard`/`scc`). When `PREQ-A-1` lands real analyzers, ALL three goldens WILL move; that future PR must regenerate via `CCE_UPDATE_RECORD_HASH_GOLDENS=1` and quote `PREQ-A-1` in the commit. The README section explicitly documents this contract so the next maintainer is not surprised.

3. **Deterministic 100k generator constraints.** The generator uses one `random.Random(seed)` instance, sorts every iterable, avoids `set` iteration without sorting, and (per Task 2 Step 1) self-asserts a baked-in content digest as the last line of the generator output. Idempotence is also verified by `diff -r` in Task 2 Step 6 and re-verified in Final Verification. This protects against the most common Python-minor-version source of fixture drift.

4. **macOS-arm64 timing noise.** GitHub `macos-15` runners are I/O-noisy and historically slower than the Linux runners for git operations. The `PNFR-PERF-1` 300s gate is **log-only** in POC-M-5 to avoid a wave of flaky warnings during the first week. POC-M-7 will tighten the gate to hard-fail after 7 consecutive nightly runs of evidence; the soft threshold and warning artifact in this plan are the data-collection mechanism for that future decision.

5. **Artifact-naming scheme.** With 3 fixtures × 3 runners = 9 hash artifacts, the previous flat `record-hash-${matrix.name}` naming would collide. The new `record-hash-<runner>-<fixture>.txt` per-file naming inside a single per-runner zip lets `compare-hashes` glob by fixture suffix and run two independent assertions (per-runner golden match + cross-runner agreement). No new GitHub Actions permissions or third-party actions are required.

6. **Dual-layer defence (per-runner golden + cross-runner grouping).** Each `(runner, fixture)` leg already asserts against the committed golden BEFORE upload (Task 5 Step 1). The downstream `compare-hashes` job adds a second, independent grouping check (Task 5 Step 2) so that even if a future refactor accidentally removes the per-leg gate, platform drift still fails the workflow. Task 5 Steps 6 and 7 negative-control both layers.

7. **No new CLI exit codes.** POC-M-5 introduces no new CLI failure modes — golden mismatches are detected by tests and CI shell logic, not by the `cce` binary. The existing exit-code map (`docs/poc-prd.md` §9.3) is unchanged. This keeps the public CLI contract stable across the milestone boundary.

8. **No scoring math changes.** Per the plan's "Does NOT touch" list, `src/cce/scoring.py`, `src/cce/canonical.py`, `src/cce/spec.py`, `src/cce/analyzer.py`, `src/cce/git_ops.py`, `src/cce/runtime.py`, and `src/cce/cli.py` are all untouched. POC-M-5 is purely a test / CI / fixture milestone, which is also the rationale for not bumping `scoring-spec.yaml::version` from `0.1.0`.
