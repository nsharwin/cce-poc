# Production Readiness Plan

> Generated from production-readiness review on 2026-05-26.
> Covers 2 critical + 5 high findings. Medium findings deferred to backlog.

---

## C-1: Fix cross-tenant record access (A01:2021 Broken Access Control)

**Severity**: Critical — data leakage across tenant boundaries
**Files**: `src/cce_service/api/service.py`, `tests/service/test_api.py`
**PRD ref**: PREQ-S-2 tenant isolation

### What's broken
`get_record(record_hash)` at line ~204 fetches a record by hash only — no tenant filter.
User in tenant A with `records:read` scope can read any record from tenant B.

### Fix
- Add `tenant` column to the `records` table/query model
- In `get_record()`, compare `principal.tenant` against `record.tenant`, raise `NotFound` on mismatch (not `Forbidden` — don't leak record existence)
- Same fix for any batch/bulk read paths (if any are added later)

### Tasks
1. [ ] Add `tenant` field to `ScoreRecord` dataclass in `storage/models.py`
2. [ ] Add `tenant` to ClickHouse `records` table DDL (new column with `ALTER TABLE ADD COLUMN … DEFAULT ''`)
3. [ ] Populate `tenant` at record write time in `service.py` `_persist_score()`
4. [ ] Add tenant-scope check in `get_record()`: `record.tenant != principal.tenant → raise NotFound`
5. [ ] Add unit test: tenant A creates record, tenant B tries to read → 404
6. [ ] Add unit test: tenant A creates record, tenant A reads → 200
7. [ ] Update in-memory `RecordRepo` to enforce tenant on `get()`

### Acceptance criteria
- Tenant B cannot read tenant A's records (404, not 403)
- Tenant A can read its own records
- Existing tests pass with updated schema

---

## C-2: Wire missing alert metrics into the codebase

**Severity**: Critical — alerts fire on non-existent signals
**Files**: `src/cce/otel.py`, `src/cce_service/dispatch/firecracker.py`, `src/cce_service/workers/consumer.py`
**PRD ref**: PREQ-O-2 Prometheus metrics

### What's broken
`cce.rules.yaml` references 3 metrics that are never emitted:
- `cce_queue_depth` → `CCEQueueDepthHigh` alert
- `cce_firecracker_boot_failures_total` → `CCEFirecrackerBootFailures` alert
- `cce_record_hash_mismatch_total` → `CCERecordHashMismatch` alert

All three alerts silently do nothing.

### Fix
Emit each metric at the correct point in the code with appropriate labels.

### Tasks
1. [ ] Add `RECORD_HASH_MISMATCH_TOTAL` Counter to `otel.py` (labels: `spec_hash`, `commit_sha`)
2. [ ] Emit `record_hash_mismatch_total.inc()` in `scoring.py:verify_record_hash()` on mismatch failure
3. [ ] Add `FIRECRACKER_BOOT_FAILURES_TOTAL` Counter to `otel.py` (labels: `reason`)
4. [ ] Emit `firecracker_boot_failures_total.inc()` in `firecracker.py` on boot failure (digest mismatch, timeout, socket error)
5. [ ] Add `QUEUE_DEPTH` Gauge to `otel.py`
6. [ ] Emit `queue_depth.set()` in `consumer.py` before/after each job pull
7. [ ] Add unit tests asserting each metric is incremented/set in the correct scenarios
8. [ ] Verify all PromQL expressions in `cce.rules.yaml` match the emitted metric names and label sets

### Acceptance criteria
- All 3 metrics appear at `/metrics` when the corresponding event occurs
- `CCERecordHashMismatch` fires when `verify_record_hash()` fails
- `CCEFirecrackerBootFailures` fires on boot failure
- `CCEQueueDepthHigh` reflects actual queue size

---

## H-1: Add retry with exponential backoff to all external calls

**Severity**: High — transient failures become permanent
**Files**: `src/cce_service/storage/postgres.py`, `src/cce_service/storage/clickhouse.py`, `src/cce/cli.py` (git clone), `src/cce_service/dispatch/firecracker.py`
**PRD ref**: PREQ-S-3 reliability

### What's broken
No retry logic anywhere. A single network blip, DNS hiccup, or temporary DB unavailability kills the job permanently.

### Fix
Wrap external calls with `tenacity` (`retry`, `stop_after_attempt`, `wait_exponential`, `retry_if_exception_type`).

### Tasks
1. [ ] Add `tenacity` to dependencies in `pyproject.toml` (POC project — check if acceptable, else write a simple retry decorator)
2. [ ] Add `@retry` to `PostgresJobRepo.create_job()` and `.update_job()` (Postgres write path)
3. [ ] Add `@retry` to `ClickHouseRecordRepo.insert()` (ClickHouse write path)
4. [ ] Add `timeout=300` to `subprocess.run(git clone ...)` in `git_ops.py`
5. [ ] Add retry wrapper around `git clone` subprocess (transient network errors)
6. [ ] In `consumer.py`, wrap `dispatch()` call with retry on `DispatchError` (max 3 attempts, exponential backoff 1s → 2s → 4s)
7. [ ] On final retry exhaustion: mark job FAILED, emit audit event, increment `JOB_FAILURES_TOTAL.labels(reason="retry_exhausted")`
8. [ ] Add unit tests for retry exhaustion path

### Acceptance criteria
- Staged, transient Postgres outage (<30s) does not cause permanent job failure
- ClickHouse insert retries on connection error
- `git clone` times out after 300s rather than hanging indefinitely
- Firecracker boot retries up to 3 times before giving up
- All retries log structured events with attempt number and backoff duration

---

## H-2: Add circuit breakers for downstream dependencies

**Severity**: High — cascading failure under load
**Files**: `src/cce_service/api/service.py`, `src/cce_service/dispatch/firecracker.py`, `src/cce_service/workers/consumer.py`
**PRD ref**: PREQ-S-4 graceful degradation

### What's broken
If ClickHouse or Firecracker is unhealthy, every incoming request still attempts to use it.
Worker keeps booting VMs that will fail.

### Fix
Circuit breaker pattern: after N consecutive failures, open the circuit for M seconds. Requests during open state fast-fail with 503.

### Tasks
1. [ ] Implement `CircuitBreaker` class (stdlib-only): thresholds for `failure_count`, `recovery_timeout_seconds`
2. [ ] Add circuit breaker around ClickHouse write path in `_persist_score()`
3. [ ] Add circuit breaker around Firecracker boot path in `dispatch()`
4. [ ] On circuit-open: log warning, emit audit event, return 503 with `Retry-After` header
5. [ ] Add `/healthz` dependency checks: DB ping + ClickHouse ping → if either fails, `/healthz` returns 503 (not 200)
6. [ ] Wire circuit breaker state into Prometheus: `cce_circuit_breaker_state{name="clickhouse|firecracker"}`
7. [ ] Add unit test: N consecutive ClickHouse failures → circuit opens → request fast-fails → after recovery_timeout → half-open → success → circuit closes
8. [ ] Add `CCECircuitBreakerOpen` alert rule to `cce.rules.yaml`

### Acceptance criteria
- After 5 consecutive ClickHouse failures, subsequent writes fast-fail for 30s
- After recovery timeout, one trial request (half-open) succeeds → circuit closes
- 503 returned with `Retry-After` header when circuit is open
- `/healthz` reflects downstream health
- Circuit state visible in Prometheus and Grafana

---

## H-3: Add timeout to git clone

**Severity**: High — hung remote blocks worker indefinitely
**Files**: `src/cce/git_ops.py`, `tests/test_git_ops.py`
**PRD ref**: PREQ-X-2 git safety

### What's broken
`subprocess.run()` for `git clone` and `git checkout` has no `timeout` parameter.
A hung remote (slow server, network stall) blocks the worker process forever.

### Fix
Add `timeout` parameter to all `subprocess.run()` calls in git operations.
Catch `subprocess.TimeoutExpired`, kill process group, raise domain exception.

### Tasks
1. [ ] Add `timeout=300` to `git clone` in `clone_remote()`
2. [ ] Add `timeout=60` to `git checkout` in `prepare_local_checkout()`
3. [ ] Add `timeout=30` to `git` subprocess calls (`rev-parse`, `rev-list`)
4. [ ] Catch `subprocess.TimeoutExpired`, call `process.kill()`, raise `GitTimeoutError(repo_url, operation, timeout_seconds)`
5. [ ] Handle `GitTimeoutError` in CLI: exit code `EXIT_GIT=12`, increment `JOB_FAILURES_TOTAL.labels(reason="git_timeout")`
6. [ ] Add unit test: mock subprocess to simulate timeout, assert `GitTimeoutError` raised

### Acceptance criteria
- `git clone` aborts after 300s with clear error
- Worker does not block indefinitely on hung remotes
- Timeout errors produce correct exit code and metrics

---

## H-4: Remove hardcoded credentials from committed files

**Severity**: High — secrets in version control
**Files**: `alembic.ini`, `ops/staging/docker-compose.yml`, `ops/staging/.env.example` (missing)
**PRD ref**: PREQ-S-5 secret management

### What's broken
- `alembic.ini` contains `postgresql+psycopg://cce:cce@localhost:5432/cce` committed
- `docker-compose.yml` defaults `CCE_PG_PASSWORD` to `cce` and ClickHouse password to empty
- `.env.example` is referenced but doesn't exist

### Fix
Replace all hardcoded defaults with environment-variable-required patterns.
Create `.env.example` with placeholder values.

### Tasks
1. [ ] Change `alembic.ini` sqlalchemy.url to `postgresql+psycopg://${CCE_PG_USER}:${CCE_PG_PASSWORD}@${CCE_PG_HOST}:${CCE_PG_PORT}/${CCE_PG_DB}`
2. [ ] Update `env.py` to read from `CCE_POSTGRES_DSN` and fail fast if not set (already partially done — verify)
3. [ ] Change `docker-compose.yml` defaults: remove `:-cce` suffix, use `${CCE_PG_PASSWORD:?required}` pattern
4. [ ] Set ClickHouse password to `${CCE_CH_PASSWORD:?required}`
5. [ ] Create `ops/staging/.env.example` with all required vars and placeholder `REPLACE_ME` values
6. [ ] Add `.env` to `.gitignore` if not already present
7. [ ] Update `ops/staging/smoke.sh` to source `.env` before running

### Acceptance criteria
- No credentials visible in any committed file under `src/` or `ops/`
- `docker compose up` fails with clear error if `.env` is missing
- `.env.example` documents all required environment variables
- Staging smoke test runs end-to-end with `.env`-provided credentials

---

## H-5: Add test coverage measurement and critical path tests

**Severity**: High — cannot quantify or trend coverage
**Files**: `pyproject.toml`, `tests/test_canonical.py` (new), `tests/test_python_analyzer.py` (new), `tests/test_cli_errors.py` (new)
**PRD ref**: POC-GATE-1 code quality

### What's broken
- No `pytest-cov` or `coverage.py` configured
- Python analyzer has zero unit tests
- CLI error paths (exit codes 10–14) never tested
- `canonical.py` never tested directly
- Service HTTP layer untested (no `TestClient`)

### Fix
Add `pytest-cov`, set minimum coverage threshold at 80%, add tests for 3 critical coverage gaps.

### Tasks
1. [ ] Add `pytest-cov` to dev dependencies in `pyproject.toml`
2. [ ] Add `[tool.coverage]` config: `source = ["src/cce"]`, `fail_under = 80`, `omit = ["src/cce_service/*"]`
3. [ ] Add `cov-default` and `cov-service` nox/pytest sessions to `pyproject.toml` scripts
4. [ ] Create `tests/test_python_analyzer.py`: test `analyse_python()` for cyclomatic, cognitive, nesting, function length on simple_python fixture
5. [ ] Create `tests/test_canonical.py`: test RFC 8785 canonicalisation for basic types, nested dicts, Unicode, edge cases
6. [ ] Create `tests/test_cli_errors.py`: test each exit code (10: bad spec, 11: digest mismatch, 12: git safety, 13: analyzer failure, 14: scoring failure)
7. [ ] Add `tests/service/test_api_http.py` using FastAPI `TestClient`: test actual HTTP layer (headers, status codes, middleware)
8. [ ] Add `--cov` to CI workflow `pytest` step for pull request runs

### Acceptance criteria
- `pytest --cov` produces a coverage report showing ≥80% on `src/cce/`
- All 5 exit codes in `test_cli_errors.py` pass
- Python analyzer tests pass with known-good fixture
- Canonical JSON edge cases tested
- CI PR runs surface coverage regressions

---

## Execution Order

| Phase | Tasks | Depends on |
|-------|-------|------------|
| **Phase 1** (today) | C-1 (tenant isolation), C-2 (missing metrics) | Nothing |
| **Phase 2** (this week) | H-3 (git timeout), H-4 (hardcoded creds) | Nothing |
| **Phase 3** (this week) | H-1 (retry), H-2 (circuit breakers) | C-2 (shares metrics infra) |
| **Phase 4** (next week) | H-5 (coverage + missing tests) | C-1 (new tests exercise tenant scope) |

### Parallel work
- C-1 and C-2 can be done simultaneously (different files)
- H-3 and H-4 are independent of everything
- H-1 and H-2 share the `otel.py` metrics setup from C-2
- H-5 should come last (exercises new error paths from H-1, H-2, H-3)
