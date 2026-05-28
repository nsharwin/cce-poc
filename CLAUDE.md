# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

CCE (Code Complexity Engine) is a **deterministic** code complexity scorer: the same commit always produces the same `record_hash` on any machine. The core invariant — byte-identical output across platforms — is the project's central design constraint. Every architectural decision flows from it.

## Commands

```bash
# Install all dependencies (including dev tooling)
uv sync

# Run the full test suite
uv run pytest -q

# Run a single test file
uv run pytest tests/test_scoring_core.py -q

# Run a single test by name
uv run pytest tests/test_scoring_core.py::test_foo -q

# Run the 100× determinism gate (slow, run before changing scoring/analyzer)
uv run pytest tests/determinism_100x.py -q

# Lint (must pass — CI enforces this)
uv run ruff check .

# Format check
uv run ruff format --check .

# Score a local repo
uv run cce score --spec ./scoring-spec.yaml --repo /path/to/repo --mode repo

# Score a specific commit
uv run cce score --spec ./scoring-spec.yaml --repo /path/to/repo --mode commit --commit <40-hex>

# Verify a produced record
uv run cce verify --record ./cce-out/<record_hash>.json
uv run cce verify --sidecar ./cce-out/<record_hash>.sha256

# Regenerate expected_record_hash.txt golden files after intentional spec changes
uv run python scripts/regenerate_expected_record_hashes.py

# Regenerate grammar span goldens after tree-sitter grammar updates
uv run python scripts/regenerate_grammar_spans.py

# Sync scoring-spec.yaml pinned_tools after rootfs rebuild
python scripts/sync_pinned_tools.py
```

## Architecture

### Core Pipeline (`src/cce/`)

The deterministic scoring core is a pure pipeline with no global state or hidden I/O:

```
git repo → prepared_repo → parse_repo → measure_metrics → build_score_record → write_outputs
```

Each stage maps to an OpenTelemetry span (`cce.load_spec`, `cce.clone`, `cce.parse`, `cce.measure`, `cce.score`, `cce.write_outputs`). The span emission order is asserted in `cli.py` with a hard `assert`.

**Key modules:**
- `spec.py` — loads and validates `scoring-spec.yaml`; computes `spec_hash` via RFC 8785 canonical JSON + SHA-256. Rejects YAML floats (all decimal values must be quoted strings).
- `analyzer.py` — splits into `parse_repo` (I/O: walks repo, reads files, verifies tool digests) and `measure_metrics` (pure: aggregates per-file metrics; no I/O). `analyse_repo` is a compatibility wrapper for both.
- `analyzers/builtin.py` — Python analyzer uses `ast` module; TypeScript uses tree-sitter with iterative DFS (no recursion, to avoid stack overflow on minified code).
- `analyzers/registry.py` — pluggable backend registry. Default backends are `builtin_ast` (Python) and `builtin_tree_sitter` (TypeScript). Production images register `lizard`/`scc` via `register_production_backends()`. `reset_registry()` is a test hook.
- `scoring.py` — uses `decimal.Decimal` with precision 28 and `ROUND_HALF_EVEN` throughout. The `record_hash` is `sha256(spec_hash ‖ commit_sha ‖ canonical_metrics_json ‖ tool_digests_json)`.
- `canonical.py` — thin wrapper around `rfc8785.dumps` (RFC 8785 JCS). Never re-implement; always use this.
- `git_ops.py` — hardened git wrappers. Every invocation uses `-c protocol.file.allow=never -c core.symlinks=false -c submodule.recurse=false`. Rejects populated `.gitmodules` and symlinks that escape the repo root.
- `runtime.py` — tool digest verification (`assert_tool_digest`) and network isolation check (`assert_network_isolated`).
- `otel.py` — soft OTel/Prometheus instrumentation. Falls back to no-ops if the SDK is absent. Never affects `record_hash`.

### Scoring Spec (`scoring-spec.yaml`)

The frozen spec defines weights, piecewise-linear normalisation cuts, rounding, and pinned tool digests. Changes to `scoring-spec.yaml` change `spec_hash` and therefore all `record_hash` values. When you update it:
1. Run `scripts/regenerate_expected_record_hashes.py` to update golden files.
2. Update `Dockerfile` and `scoring-spec.yaml::worker_image` atomically in one commit if the base image changes.

### Optional Service Layer (`src/cce_service/`)

FastAPI REST wrapper around the core — only installed via `uv pip install -e '.[cce-service]'`. Heavy dependencies (FastAPI, Postgres, ClickHouse, Redis, Firecracker) are lazy-imported so the core remains testable without infrastructure.

- `api/app.py` — FastAPI routes, body-size middleware, metrics auth.
- `api/service.py` — `ScoreService`: business logic between HTTP and storage.
- `dispatch/base.py` — `Dispatcher` Protocol + `InProcessDispatcher` (test-only).
- `dispatch/firecracker.py` — production Firecracker microVM dispatcher.
- `storage/` — Postgres (jobs, audit) + ClickHouse (scoring records) adapters, with in-memory fakes for tests.
- `auth/` — OAuth2 client-credentials JWT with scopes `score:write`, `records:read`, `audit:read`.
- `migrations/` — Alembic migrations.

### Test Suite (`tests/`)

- `conftest.py` — sets `CCE_ENV=development` for all tests (required for auth constructors).
- `determinism_100x.py` — runs scoring 100× and asserts all hashes collapse to one.
- `tests/fixtures/` — `simple_python`, `simple_typescript`, `perf_100k` (generated). Each has `expected_record_hash.txt` as a frozen golden.
- `test_expected_record_hashes.py` — asserts live scoring matches the frozen golden files.
- `test_grammar_stability.py` — asserts tree-sitter parse spans match frozen goldens in `tests/_grammar_spans.py`.
- `test_submodule_trap.py` — verifies `.gitmodules` rejection.
- `tests/service/` — service-layer tests using in-memory fakes (no real DB required).

## Critical Invariants

**Do not break these without understanding the full impact:**

1. **No floats in scoring-spec.yaml** — `spec.py` hard-rejects them. All decimal values must be quoted strings (e.g. `'0.30'`, not `0.30`).
2. **Decimal arithmetic only** — `scoring.py` uses `decimal.Decimal` with `ROUND_HALF_EVEN` throughout. Never introduce `float` into scoring math.
3. **Canonical JSON via `rfc8785`** — always use `cce.canonical.canonical_json_bytes()`. Never substitute `json.dumps`.
4. **Span order is asserted** — `cli.py` has a hard `assert` on timing order `[load_spec, clone, parse, measure, score, total]`. Do not reorder stages.
5. **`measure_metrics` must be pure** — no I/O, no env access, no time. Only `parse_repo` may perform I/O.
6. **Digest verification before any file read** — `parse_repo` calls `registry.assert_digests()` exactly once before reading any file.
7. **Atomic file writes** — `_write_outputs` uses `os.replace()` via temp files. Maintain this pattern.

## Environment Variables

| Variable | Effect |
|---|---|
| `CCE_REQUIRE_NETWORK_ISOLATED=1` | Hard-fail if outbound network is reachable |
| `CCE_ENV=development` | Bypasses auth strict-mode (set by conftest for all tests) |
| `CCE_METRICS_TOKEN` | Bearer token for `/metrics` endpoint |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint (spans) |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Takes precedence over generic endpoint |
| `OTEL_SERVICE_NAME` | Defaults to `cce` |

## CI Workflows

- `poc-determinism.yml` — runs on every push/PR; scores fixtures on linux-x86_64, linux-arm64, and macos-arm64 both natively and inside the pinned Docker container; asserts all produce the same frozen hash.
- `nightly-stability.yml` — 06:00 UTC cron; enforces a 7-day green streak tracked in `ops/nightly-streak.json`.
- `perf-gate.yml` — 100k LoC must score in ≤ 90 s and ≤ 2 GB RAM.

## Conventions

- All dependencies are managed with `uv`. Do not use `pip install` directly.
- The `src/` layout is used — `pythonpath = ["src"]` is in `pyproject.toml`. No `sys.path` hacks needed in application code.
- `cce_service` extras are not installed by default; tests that import from it guard imports or use conditional skips.
- `CCE_RUN_PERF=1` is required to enable perf tests (they are slow and generate large fixtures).
- When adding a new analyzer backend, register it via `register_production_backends()`, not by modifying `default_registry()`.
