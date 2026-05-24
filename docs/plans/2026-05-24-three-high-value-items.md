# Three High-Value Items Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close three high-value deferred gaps: fix packaging so `uv run pytest` works, add cross-runner record-hash comparison to CI (PREQ-S-7), and replace the TypeScript regex heuristic analyzer with real tree-sitter AST parsing (PREQ-A-1 partial).

**Architecture:** Item 1 is a one-line pyproject.toml change. Item 2 extends the existing `.github/workflows/poc-determinism.yml` with score + upload + compare steps. Item 3 adds `tree-sitter-language-pack` to deps and rewrites `src/cce/analyzer.py`'s TypeScript path to use the real grammar; Python keeps using `ast`.

**Tech Stack:** Python 3.12, uv, pytest, tree-sitter>=0.24, tree-sitter-language-pack, GitHub Actions, rfc8785, decimal

---

## Item 1: Fix pyproject.toml Packaging

Fixes the warning "Skipping installation of entry points" so both `uv run pytest` and `uv run cce` work.

**Files:**
- Modify: `pyproject.toml`

### Task 1.1: Enable uv packaging

**Step 1: Add `tool.uv.package = true` to pyproject.toml**

Open `pyproject.toml` and add this block after `[project]`:

```toml
[tool.uv]
package = true
```

Also add a minimal build backend so uv can build a wheel:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

The full file should look like:

```toml
[project]
name = "cce-poc"
version = "0.1.0"
description = "Proof of concept for deterministic code complexity scoring."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "PyYAML==6.0.3",
    "rfc8785==0.1.4",
]

[project.scripts]
cce = "cce.cli:entrypoint"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = true

[dependency-groups]
dev = [
    "hatchling",
    "pytest==9.0.3",
    "ruff==0.15.14",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

**Step 2: Sync and verify**

```bash
uv sync
uv run pytest -q
```

Expected: 6 passed, no "Skipping installation" warning.

**Step 3: Verify CLI entry point works**

```bash
uv run cce --help
```

Expected: prints usage without error.

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "fix: enable uv packaging so entry points install correctly"
```

---

## Item 2: Cross-Runner Record-Hash Comparison (PREQ-S-7)

The existing workflow runs tests on 3 runners but never scores a real repo and compares the resulting `record_hash` values. This task wires that gate.

**Files:**
- Modify: `.github/workflows/poc-determinism.yml`
- Create: `tests/fixtures/simple_python/pkg/example.py` (scoring fixture)

### Task 2.1: Create a stable scoring fixture

This is a tiny Python file committed to the repo. Its content must never change after this commit — it's the canonical fixture for cross-runner comparison.

**Step 1: Create the fixture file**

```bash
mkdir -p tests/fixtures/simple_python/pkg
```

Create `tests/fixtures/simple_python/pkg/example.py`:

```python
def score(value):
    if value > 10:
        for item in range(value):
            if item % 2 == 0:
                return item
    return 0
```

**Step 2: Verify the fixture scores deterministically locally**

```bash
cd tests/fixtures/simple_python && git init && git config user.email "cce@example.test" && git config user.name "CCE Test" && git add . && git commit -m "fixture" && cd ../../..
```

Then score it:

```bash
uv run cce score \
  --spec ./scoring-spec.yaml \
  --repo ./tests/fixtures/simple_python \
  --mode repo \
  --out /tmp/cce-fixture-out \
  --verify-digests false
```

Expected: prints a `sha256:...` hash and exits 0. Note the hash — it will be the same on every runner.

**Step 3: Commit the fixture**

```bash
git add tests/fixtures/
git commit -m "test: add stable Python fixture for cross-runner hash comparison"
```

### Task 2.2: Extend the CI workflow

**Step 1: Write the updated workflow**

Replace `.github/workflows/poc-determinism.yml` with:

```yaml
name: POC Determinism

on:
  push:
  pull_request:
  workflow_dispatch:

jobs:
  deterministic-core:
    name: ${{ matrix.name }}
    runs-on: ${{ matrix.runner }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: linux-x86_64
            runner: ubuntu-24.04
          - name: linux-arm64
            runner: ubuntu-24.04-arm
          - name: macos-arm64
            runner: macos-15
    steps:
      - name: Checkout
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd

      - name: Install uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b
        with:
          version: "0.9.27"

      - name: Install Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync

      - name: Run unit tests
        run: uv run pytest -q

      - name: Run PREQ-S-6 determinism gate
        run: uv run pytest tests/determinism_100x.py -q

      - name: Init fixture git repo
        run: |
          cd tests/fixtures/simple_python
          git init
          git config user.email "cce@example.test"
          git config user.name "CCE Test"
          git add .
          git commit -m "fixture"

      - name: Score fixture repo (PREQ-S-7)
        run: |
          mkdir -p cce-out
          HASH=$(uv run cce score \
            --spec ./scoring-spec.yaml \
            --repo ./tests/fixtures/simple_python \
            --mode repo \
            --out ./cce-out \
            --verify-digests false)
          echo "$HASH" > cce-out/record_hash.txt
          echo "RECORD_HASH=$HASH" >> "$GITHUB_ENV"

      - name: Upload record hash artifact
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: record-hash-${{ matrix.name }}
          path: cce-out/record_hash.txt

  compare-hashes:
    name: Compare record hashes across runners
    runs-on: ubuntu-24.04
    needs: deterministic-core
    steps:
      - name: Download all hash artifacts
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093
        with:
          path: hash-artifacts

      - name: Assert all hashes match
        run: |
          set -euo pipefail
          echo "=== Collected hashes ==="
          find hash-artifacts -name "record_hash.txt" -exec sh -c 'echo "$1: $(cat $1)"' _ {} \;
          UNIQUE=$(find hash-artifacts -name "record_hash.txt" -exec cat {} \; | sort -u | wc -l)
          echo "Unique hashes: $UNIQUE"
          if [ "$UNIQUE" -ne 1 ]; then
            echo "FAIL: runners produced different record hashes"
            exit 1
          fi
          echo "PASS: all runners agree on record hash"
```

**Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/poc-determinism.yml'))" && echo OK
```

Expected: `OK`

**Step 3: Commit**

```bash
git add .github/workflows/poc-determinism.yml
git commit -m "ci: add cross-runner record-hash comparison gate (PREQ-S-7)"
```

---

## Item 3: Replace TypeScript Regex Analyzer with tree-sitter (PREQ-A-1 partial)

The current TypeScript path in `src/cce/analyzer.py` counts branch keywords with a regex and infers function boundaries by scanning for `function ` or `=>`. Real cyclomatic/cognitive complexity requires an AST. This replaces that with `tree-sitter-language-pack` which ships pre-built grammars as Python wheels, giving deterministic results with no compile step.

**Files:**
- Modify: `pyproject.toml` (add dep)
- Modify: `src/cce/analyzer.py` (new TS analyzer)
- Modify: `tests/test_scoring_core.py` (update fixture if needed)
- Create: `tests/test_analyzer.py` (new targeted tests)

### Task 3.1: Add tree-sitter dependency

**Step 1: Add to pyproject.toml dependencies**

In `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "PyYAML==6.0.3",
    "rfc8785==0.1.4",
    "tree-sitter==0.24.0",
    "tree-sitter-language-pack==0.7.2",
]
```

Pin both versions exactly — determinism requires it.

**Step 2: Sync and verify install**

```bash
uv sync
uv run python -c "import tree_sitter_language_pack; print('ok')"
```

Expected: `ok`

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add tree-sitter and tree-sitter-language-pack for real TS AST parsing"
```

### Task 3.2: Write failing tests for the new TypeScript analyzer

The existing test suite has no test for the TypeScript path. Write targeted tests first.

**Step 1: Create `tests/test_analyzer.py`**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from cce.analyzer import _analyse_typescript


def test_empty_file_returns_zero_metrics() -> None:
    result = _analyse_typescript("")
    assert result["cyclomatic"] == 1
    assert result["cognitive"] == 0
    assert result["nesting_depth"] == 0
    assert result["function_length"] == 0


def test_simple_function_cyclomatic_one() -> None:
    src = """\
function greet(name: string): string {
    return `Hello, ${name}`;
}
"""
    result = _analyse_typescript(src)
    assert result["cyclomatic"] == 1


def test_if_inside_function_increments_cyclomatic() -> None:
    src = """\
function check(x: number): boolean {
    if (x > 0) {
        return true;
    }
    return false;
}
"""
    result = _analyse_typescript(src)
    assert result["cyclomatic"] == 2


def test_nested_if_increments_cognitive_more() -> None:
    src = """\
function nested(x: number, y: number): number {
    if (x > 0) {
        if (y > 0) {
            return x + y;
        }
    }
    return 0;
}
"""
    result = _analyse_typescript(src)
    # cognitive: outer if = 1, inner if = 1 + 1 (nesting penalty) = 3 total
    assert result["cognitive"] >= result["cyclomatic"]
    assert result["nesting_depth"] == 2


def test_function_length_counts_lines() -> None:
    src = """\
function long(): void {
    const a = 1;
    const b = 2;
    const c = 3;
    const d = 4;
}
"""
    result = _analyse_typescript(src)
    assert result["function_length"] == 6  # 6 lines from function to closing brace


def test_arrow_function_detected() -> None:
    src = """\
const double = (x: number): number => {
    return x * 2;
};
"""
    result = _analyse_typescript(src)
    assert result["function_length"] > 0


def test_deterministic_on_repeated_calls() -> None:
    src = """\
function score(value: number): number {
    if (value > 10) {
        for (let i = 0; i < value; i++) {
            if (i % 2 === 0) {
                return i;
            }
        }
    }
    return 0;
}
"""
    results = [_analyse_typescript(src) for _ in range(10)]
    assert len({str(r) for r in results}) == 1
```

**Step 2: Run tests to see them fail**

```bash
uv run pytest tests/test_analyzer.py -v
```

Expected: most tests FAIL or ERROR because `_analyse_typescript` is still the regex version.

### Task 3.3: Implement the tree-sitter TypeScript analyzer

tree-sitter gives us a real CST. We walk it to count:
- **cyclomatic:** 1 + count of `if_statement`, `else_if_clause`, `for_statement`, `while_statement`, `do_statement`, `switch_case`, `ternary_expression`, `catch_clause`, `&&`, `||`, `??`
- **cognitive:** sum of (1 + nesting_depth) for each branch node
- **nesting_depth:** max depth of nested branch nodes
- **function_length:** lines spanned by each `function_declaration`, `arrow_function`, `method_definition`

**Step 1: Replace `_analyse_typescript` and `_typescript_function_lengths` in `src/cce/analyzer.py`**

Add these imports at the top (keep existing imports):

```python
import tree_sitter_language_pack
from tree_sitter import Language, Node, Parser
```

Add these module-level constants after the existing `_TS_BRANCH_RE` line:

```python
_TS_LANGUAGE: Language | None = None

_TS_BRANCH_TYPES = frozenset(
    {
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "switch_case",
        "ternary_expression",
        "catch_clause",
        "binary_expression",  # filtered to && || ?? below
    }
)

_TS_LOGICAL_OPERATORS = frozenset({"&&", "||", "??"})

_TS_FUNCTION_TYPES = frozenset(
    {"function_declaration", "function_expression", "arrow_function", "method_definition"}
)
```

Add a lazy initialiser (avoids import-time cost):

```python
def _ts_language() -> Language:
    global _TS_LANGUAGE
    if _TS_LANGUAGE is None:
        _TS_LANGUAGE = Language(tree_sitter_language_pack.get_language("typescript"))
    return _TS_LANGUAGE
```

Replace the entire `_analyse_typescript` function and remove `_typescript_function_lengths`:

```python
def _analyse_typescript(text: str) -> dict[str, int]:
    if not text.strip():
        return {
            "cyclomatic": 1,
            "cognitive": 0,
            "nesting_depth": 0,
            "function_length": 0,
            "file_length": 0,
        }
    parser = Parser(_ts_language())
    tree = parser.parse(text.encode("utf-8"))

    function_results: list[dict[str, int]] = []
    _walk_ts_functions(tree.root_node, function_results, text)

    if not function_results:
        return {
            "cyclomatic": 1,
            "cognitive": 0,
            "nesting_depth": 0,
            "function_length": 0,
            "file_length": 0,
        }

    return {
        "cyclomatic": max(r["cyclomatic"] for r in function_results),
        "cognitive": max(r["cognitive"] for r in function_results),
        "nesting_depth": max(r["nesting_depth"] for r in function_results),
        "function_length": max(r["function_length"] for r in function_results),
        "file_length": 0,  # caller sets this
    }


def _walk_ts_functions(
    node: Node,
    results: list[dict[str, int]],
    source: str,
) -> None:
    if node.type in _TS_FUNCTION_TYPES:
        cyclomatic, cognitive, max_depth = _count_ts_function(node, source)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        results.append(
            {
                "cyclomatic": cyclomatic,
                "cognitive": cognitive,
                "nesting_depth": max_depth,
                "function_length": end_line - start_line + 1,
            }
        )
    for child in node.children:
        _walk_ts_functions(child, results, source)


def _count_ts_function(node: Node, source: str) -> tuple[int, int, int]:
    cyclomatic = 1
    cognitive = 0
    max_depth = 0

    def walk(n: Node, depth: int) -> None:
        nonlocal cyclomatic, cognitive, max_depth
        is_branch = False
        if n.type in _TS_BRANCH_TYPES:
            if n.type == "binary_expression":
                op_node = next(
                    (c for c in n.children if c.type == "binary_operator"),
                    None,
                )
                op_text = source[op_node.start_byte:op_node.end_byte] if op_node else ""
                if op_text not in _TS_LOGICAL_OPERATORS:
                    for child in n.children:
                        walk(child, depth)
                    return
            if n.type == "else_clause":
                child_types = {c.type for c in n.children}
                if "if_statement" in child_types:
                    cyclomatic += 1
                    cognitive += 1
                    for child in n.children:
                        walk(child, depth)
                    return
            is_branch = True
            cyclomatic += 1
            cognitive += 1 + depth
            new_depth = depth + 1
            max_depth = max(max_depth, new_depth)
            for child in n.children:
                walk(child, new_depth)
            return
        if n.type in _TS_FUNCTION_TYPES and n is not node:
            return  # don't recurse into nested functions
        if not is_branch:
            for child in n.children:
                walk(child, depth)

    for child in node.children:
        walk(child, 0)
    return cyclomatic, cognitive, max_depth
```

**Step 2: Run the new tests**

```bash
uv run pytest tests/test_analyzer.py -v
```

Expected: all 7 tests pass.

**Step 3: Run the full suite to check for regressions**

```bash
uv run pytest -q
```

Expected: all tests pass (6 original + 7 new = 13 total).

**Step 4: Commit**

```bash
git add src/cce/analyzer.py tests/test_analyzer.py
git commit -m "feat: replace TypeScript regex heuristics with tree-sitter AST analyzer (PREQ-A-1 partial)"
```

### Task 3.4: Update DEFERRED.md to reflect partial closure

**Step 1: Edit `DEFERRED.md`**

Change the `PREQ-A-1` / `REQ-A-1` line from:

```
- `PREQ-A-1` / `REQ-A-1`: Real `tree-sitter`, `tree-sitter-python`, `tree-sitter-typescript`, `lizard`, and `scc` artifact digest verification is not wired yet. The current code validates sha256 digest shapes only.
```

To:

```
- `PREQ-A-1` / `REQ-A-1` (partial): TypeScript now uses real `tree-sitter-language-pack` grammar. Python keeps using `ast`. `lizard` and `scc` metrics and artifact digest verification are not wired yet — wheel digests are still validated for shape only.
```

**Step 2: Commit**

```bash
git add DEFERRED.md
git commit -m "docs: update DEFERRED.md to reflect partial PREQ-A-1 closure"
```

---

## Final Verification

Run the full suite one last time:

```bash
uv run pytest -q
uv run pytest tests/determinism_100x.py -q
uv run cce score --spec ./scoring-spec.yaml --repo . --mode repo --out /tmp/cce-self --verify-digests false
```

Expected: all tests pass, CLI exits 0 and prints a `sha256:` hash.

---

## Commit Summary

| # | Message | Closes |
|---|---------|--------|
| 1 | `fix: enable uv packaging so entry points install correctly` | packaging warning |
| 2 | `test: add stable Python fixture for cross-runner hash comparison` | PREQ-S-7 prep |
| 3 | `ci: add cross-runner record-hash comparison gate (PREQ-S-7)` | PREQ-S-7 |
| 4 | `deps: add tree-sitter and tree-sitter-language-pack for real TS AST parsing` | PREQ-A-1 dep |
| 5 | `feat: replace TypeScript regex heuristics with tree-sitter AST analyzer (PREQ-A-1 partial)` | PREQ-A-1 |
| 6 | `docs: update DEFERRED.md to reflect partial PREQ-A-1 closure` | housekeeping |
