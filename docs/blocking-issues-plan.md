# Blocking Issues — Comprehensive Remediation Plan

> **Generated**: 2026-05-27
> **Cross-references**: `production-readiness-plan.md` (C-1, C-2, H-1–H-5), `medium-findings-plan.md` (M-1–M-14)
> **New findings**: B-1 through B-8 (8 blocking issues discovered in code review)

---

## Issue Inventory

### Critical (C) — Covered by `production-readiness-plan.md`

| ID | Title | Plan Ref |
|----|-------|----------|
| C-1 | Cross-tenant record access (A01:2021) | `production-readiness-plan.md` §C-1 |
| C-2 | Missing alert metrics wired into codebase | `production-readiness-plan.md` §C-2 |

### High (H) — Covered by `production-readiness-plan.md`

| ID | Title | Plan Ref |
|----|-------|----------|
| H-1 | Retry with exponential backoff on external calls | `production-readiness-plan.md` §H-1 |
| H-2 | Circuit breakers for downstream dependencies | `production-readiness-plan.md` §H-2 |
| H-3 | Timeout on git clone | `production-readiness-plan.md` §H-3 |
| H-4 | Hardcoded credentials in committed files | `production-readiness-plan.md` §H-4 |
| H-5 | Test coverage measurement + critical-path tests | `production-readiness-plan.md` §H-5 |

### Medium (M) — Covered by `medium-findings-plan.md`

| ID | Title | Plan Ref |
|----|-------|----------|
| M-1 | Audit tenant scoping | `medium-findings-plan.md` §M-1 |
| M-2 | Structured JSON logging | `medium-findings-plan.md` §M-2 |
| M-3 | Correlation IDs | `medium-findings-plan.md` §M-3 |
| M-4 | Postgres connection pool tuning | `medium-findings-plan.md` §M-4 |
| M-5 | ClickHouse adapter timeouts + write retry | `medium-findings-plan.md` §M-5 |
| M-6 | FastAPI request body size limit | `medium-findings-plan.md` §M-6 |
| M-7 | HTTPS-only repo URLs | `medium-findings-plan.md` §M-7 |
| M-8 | Docker service hardening | `medium-findings-plan.md` §M-8 |
| M-9 | HS256 production guardrail | `medium-findings-plan.md` §M-9 |
| M-10 | jailer.json digest injection | `medium-findings-plan.md` §M-10 |
| M-11 | N-1 storage compatibility test | `medium-findings-plan.md` §M-11 |
| M-12 | Production K8s manifests | `medium-findings-plan.md` §M-12 |
| M-13 | SBOM generation in CI | `medium-findings-plan.md` §M-13 |
| M-14 | Docker HEALTHCHECK | `medium-findings-plan.md` §M-14 |

### Blocking (B) — **NEW** — Not covered by any existing plan

| ID | Title | Severity | File |
|----|-------|----------|------|
| **B-1** | Firecracker Popen stdout/stderr pipe deadlock | **Critical** | `firecracker.py:148` |
| **B-2** | CircuitBreaker has no synchronisation (claims thread-safety) | **Critical** | `circuit_breaker.py:30` |
| **B-3** | No JWKS-based JWT verifier for production (HS256 only) | **Critical** | `auth/jwt.py` |
| **B-4** | No NetworkPolicy in K8s manifests | **High** | `ops/k8s/` |
| **B-5** | Disk write failures after scoring are unhandled | **High** | `cli.py:247-261` |
| **B-6** | spec_ref has no path-traversal protection | **High** | `service.py:133` |
| **B-7** | Recursive tree walk can overflow stack on deep TS files | **High** | `builtin.py:96-107` |
| **B-8** | REGISTRY singleton not thread-safe (TOCTOU race) | **High** | `registry.py:96-100` |

---

## New Finding Details

### B-1: Firecracker Popen stdout/stderr pipe deadlock — `firecracker.py:148`

**Severity**: Critical — deadlock renders Firecracker dispatcher unusable under any non-trivial output.

**Root cause**: `subprocess.Popen` is called with `stdout=subprocess.PIPE, stderr=subprocess.PIPE`. OS pipe buffers are finite (~64 KiB on Linux). If the firecracker/jailer process writes more than the buffer capacity before the parent reads from the pipes, the child process blocks in `write(2)` waiting for the parent to drain the pipe. The parent is blocked waiting for the API socket to appear. Classic circular deadlock. The only `communicate()` call is on the error path (line 162), and even then only stderr is read. On the happy path, pipes are **never drained**.

**Fix**: Redirect stdout/stderr to `subprocess.DEVNULL` and pass `--log-path` to the jailer for diagnostics. On error, read the log file instead of stderr.

**Tasks**:
1. [ ] Change `Popen` `stdout=subprocess.PIPE, stderr=subprocess.PIPE` → `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`
2. [ ] Add `--log-path` argument to jailer command pointing to `workdir / "firecracker.log"`
3. [ ] On error path, read `workdir / "firecracker.log"` instead of `self._fc_process.stderr`
4. [ ] Update docstring to note log output location

**Acceptance**: `_spawn_vm` never deadlocks regardless of firecracker/jailer output volume.

---

### B-2: CircuitBreaker has no synchronisation — `circuit_breaker.py:30`

**Severity**: Critical — data races on `_state`, `_failure_count`, `_last_failure_time` under concurrent access.

**Root cause**: The docstring claims "Thread-safe circuit breaker." Implementation uses plain Python attribute reads/writes with zero synchronisation. Under concurrent `call()` invocations: lost counter increments, torn state reads, TOCTOU on `_maybe_transition()`.

**Fix**: Add a `threading.Lock`. Hold the lock for state reads/mutations but release it before calling the downstream function (don't block state reads on slow I/O).

**Tasks**:
1. [ ] Add `import threading` and `self._lock = threading.Lock()` in `__init__`
2. [ ] Acquire lock in `call()` for state read + `_maybe_transition()` + open check
3. [ ] Release lock before `func(*args, **kwargs)` call
4. [ ] Re-acquire lock for state mutation on success/failure
5. [ ] Add `@property` accessors for `state` and `failure_count` that acquire lock

**Acceptance**:
- 10 threads increment failures concurrently → `failure_count == 10` (no lost increments)
- Circuit opens at exactly `failure_threshold`
- Half-open → success → closed transition is atomic

---

### B-3: No JWKS-based JWT verifier exists for production — `auth/jwt.py`

**Severity**: Critical — M-9 adds a guardrail that prevents HS256 in production but provides no alternative. Production auth is a dead-end.

**Fix**: Implement `JwksVerifier` in a new file `src/cce_service/auth/jwks.py`. Accept `jwks_uri`, `issuer`, `audience`, `cache_ttl`. Fetch JWKS on first verification; cache with TTL. Validate `kid`, `alg` ∈ {RS256, ES256}, `iss`/`aud`/`exp`/`nbf`. Return `Principal` (same type, polymorphic). Refactor the service layer's `verifier` parameter to accept a `Protocol` that both HS256 and JWKS verifiers satisfy.

**Tasks**:
1. [ ] Create `src/cce_service/auth/jwks.py` with `JwksVerifier` class
2. [ ] Add `cryptography` (or `PyJWT[crypto]`) to `cce-service` extras in `pyproject.toml`
3. [ ] Implement JWKS fetch with TTL cache (stdlib `urllib` or `httpx`)
4. [ ] Validate RS256/ES256 signatures against the matching JWK
5. [ ] Refactor `ScoreService.__init__` to accept a `JwtVerifierProtocol` instead of concrete `JwtVerifier`
6. [ ] Add unit tests with a static JWKS fixture (offline)
7. [ ] Add integration test with `jwt.io`-generated RS256 tokens

**Acceptance**: Production can run with `CCE_JWKS_URI=https://...` and RS256 tokens. HS256 remains for dev/test only.

---

### B-4: No NetworkPolicy in K8s manifests — `ops/k8s/`

**Severity**: High — zero pod-to-pod network restrictions. Worker pods can reach API/DB pods without restriction.

**Fix**: Add `ops/k8s/network-policy.yaml` with default-deny-all plus explicit allows: API → Postgres (5432) + ClickHouse (8123, 9000) + OTel (4318) + DNS (53/UDP); Worker → same destinations; Ingress controller → API (8080). Worker pods get no ingress.

**Tasks**:
1. [ ] Create `ops/k8s/network-policy.yaml` with deny-all default
2. [ ] Add `cce-api-allow` NetworkPolicy: ingress from ingress-controller NS, egress to Postgres + ClickHouse + OTel + DNS
3. [ ] Add `cce-worker-allow` NetworkPolicy: egress to Postgres + ClickHouse + OTel + DNS only; no ingress
4. [ ] Update `ops/k8s/README.md` with apply order (NetworkPolicy after Deployments)

**Acceptance**: Worker pods cannot reach API pods. API pods cannot reach worker pods. Both can reach databases. DNS resolution works.

---

### B-5: Disk write failures after scoring are unhandled — `cli.py:247-261`

**Severity**: High — successful scoring computation is lost because write phase has no error handling.

**Fix**: Wrap each write in try/except. On failure, increment `JOB_FAILURES_TOTAL.labels(reason="write_output")` and exit with `EXIT_WRITE = 15`. Use atomic writes (write to temp, then `os.replace()`) so partial files are never left behind.

**Tasks**:
1. [ ] Add `EXIT_WRITE = 15` to `cli.py` exit code constants
2. [ ] Implement `_atomic_write()` helper: write to `.tmp`, `os.replace()` to target
3. [ ] Wrap `_write_outputs()` body in try/except for each file
4. [ ] On `OSError`: `JOB_FAILURES_TOTAL.labels(reason="write_output").inc()`, log error, raise `_Exit(EXIT_WRITE)`
5. [ ] Add unit test with mock `Path.write_bytes` raising `OSError`

**Acceptance**: Disk-full scenario produces clean exit code 15 + metric increment, not a raw traceback. No partial `.json` files.

---

### B-6: spec_ref has no path-traversal protection — `service.py:133`

**Severity**: High — attacker with `score:write` scope can read arbitrary files from worker filesystem.

**Fix**: Reject `spec_ref` containing `..` or starting with `/`. In the Firecracker dispatcher, resolve the path and assert it's within an allowed directory.

**Tasks**:
1. [ ] Add validation in `create_score()`: reject `..`, leading `/`, non-alphanumeric (except `._-/`)
2. [ ] Add `_RESOLVED_SPEC_BASE` config to Firecracker dispatcher (default: `/var/lib/cce/specs`)
3. [ ] In `_send_job()`: `Path(spec_ref).resolve()` and assert it's within `_RESOLVED_SPEC_BASE`
4. [ ] Add unit test: `../../etc/passwd` → `BadRequest`
5. [ ] Add unit test: valid spec path → accepted

**Acceptance**: Path traversal attempts rejected at API layer. Resolved path checked at dispatch layer (defense in depth).

---

### B-7: Recursive tree walk can overflow stack on deep TS files — `builtin.py:96-107`

**Severity**: High — deeply nested TypeScript can crash the analyzer with `RecursionError`.

**Fix**: Convert `_walk_ts_functions()` and inner `walk()` in `_count_ts_function()` from recursive DFS to iterative using an explicit stack. Add a `MAX_NESTING_DEPTH = 256` guard.

**Tasks**:
1. [ ] Rewrite `_walk_ts_functions()` with `stack = [node]` and `while stack:` loop
2. [ ] Rewrite inner `walk()` in `_count_ts_function()` the same way
3. [ ] Add `MAX_NESTING_DEPTH = 256` — stop descending past this depth
4. [ ] Add unit test: generate a deeply-nested TS file (500 nested if/else blocks) → no `RecursionError`

**Acceptance**: 500+ nested nodes processed without stack overflow. Metrics remain byte-identical to the recursive version for normal-depth files.

---

### B-8: REGISTRY singleton not thread-safe — `registry.py:96-100`

**Severity**: High — concurrent `get_registry()` calls can create duplicate registries.

**Fix**: Add `threading.Lock` with double-checked locking pattern.

**Tasks**:
1. [ ] Add `_REGISTRY_LOCK = threading.Lock()`
2. [ ] Rewrite `get_registry()` with fast-path read check, then lock + double-check
3. [ ] Rewrite `reset_registry()` with lock acquisition
4. [ ] Add unit test: 10 threads call `get_registry()` concurrently → all return same object

**Acceptance**: Single registry instance regardless of concurrent calls. `reset_registry` + concurrent `get_registry` race resolved.

---

## Phased Execution Plan

### Phase 1 — Critical Fixes (Must Ship Before Any Production Traffic)

| Task | Issue ID | Effort | File(s) |
|------|----------|--------|---------|
| T1.1 | B-2: CircuitBreaker synchronisation | Small | `circuit_breaker.py` |
| T1.2 | B-1: Firecracker Popen pipe deadlock | Small | `firecracker.py` |
| T1.3 | B-8: REGISTRY singleton thread-safety | Small | `registry.py` |
| T1.4 | B-3: JWKS-based JWT verifier | Large | `auth/jwks.py` (new), `auth/jwt.py`, `service.py` |
| T1.5 | C-1: Cross-tenant record access | Medium | `service.py`, `storage/`, `tests/` |
| T1.6 | C-2: Missing alert metrics | Medium | `otel.py`, `firecracker.py`, `consumer.py` |

**Phase 1 Acceptance Gate**: All critical bugs fixed. JWKS verifier tested with real JWKS endpoint. No data races in production paths.

---

### Phase 2 — Security Hardening

| Task | Issue ID | Effort | Depends On |
|------|----------|--------|------------|
| T2.1 | B-6: spec_ref path-traversal protection | Small | — |
| T2.2 | B-7: Recursive tree walk → iterative | Medium | — |
| T2.3 | B-4: K8s NetworkPolicy | Medium | M-12 (K8s manifests) |
| T2.4 | M-6: Request body size limit | Small | — |
| T2.5 | M-7: HTTPS-only repo URLs | Small | — |
| T2.6 | M-9: HS256 production guardrail | Small | B-3 (JWKS verifier) |
| T2.7 | H-4: Hardcoded credentials | Medium | — |

**Phase 2 Acceptance Gate**: OWASP top-10 addressed. Path-traversal blocked. No stack overflow on adversarial input. Network segmentation enforced.

---

### Phase 3 — Reliability Engineering

| Task | Issue ID | Effort | Depends On |
|------|----------|--------|------------|
| T3.1 | B-5: Disk write failure handling | Small | — |
| T3.2 | H-1: Retry with exponential backoff | Large | — |
| T3.3 | H-2: Circuit breaker wiring (downstream deps) | Medium | B-2 |
| T3.4 | H-3: Git clone timeout | Small | — |
| T3.5 | M-1: Audit tenant scoping | Small | C-1 |
| T3.6 | M-4: Postgres pool tuning | Small | — |
| T3.7 | M-5: ClickHouse timeouts + retry | Small | H-1 |

**Phase 3 Acceptance Gate**: Transient failures handled gracefully. No permanent job loss from single network blip.

---

### Phase 4 — Observability & Operations

| Task | Issue ID | Effort | Depends On |
|------|----------|--------|------------|
| T4.1 | M-2: Structured JSON logging | Medium | — |
| T4.2 | M-3: Correlation IDs | Medium | M-2 |
| T4.3 | M-8: Docker hardening (read-only rootfs) | Medium | — |
| T4.4 | M-10: jailer.json digest injection | Medium | — |
| T4.5 | M-12: K8s manifests | Large | — |
| T4.6 | M-14: Docker HEALTHCHECK | Small | M-8 |
| T4.7 | H-5: Test coverage + critical-path tests | Large | All above |

**Phase 4 Acceptance Gate**: All alerts have matching metrics. Logs machine-parseable. K8s manifests deployable end-to-end.

---

### Phase 5 — Compliance & Documentation

| Task | Issue ID | Effort | Depends On |
|------|----------|--------|------------|
| T5.1 | M-11: N-1 storage compatibility test | Medium | — |
| T5.2 | M-13: SBOM generation in CI | Small | — |
| T5.3 | Update `DEFERRED.md` and `README.md` | Small | All above |

**Phase 5 Acceptance Gate**: SBOM per build. N-1 compat verified. Documentation current.

---

## Parallelisation Opportunities

**Within Phase 1**:
- T1.1, T1.2, T1.3 are all independent single-file fixes — parallel
- T1.4 is independent of the others — parallel
- T1.5 and T1.6 share no files — parallel

**Within Phase 2**:
- T2.1, T2.2, T2.4, T2.5 are all independent — parallel
- T2.6 depends on B-3 (Phase 1)
- T2.3 depends on M-12 (Phase 4 — can be pulled forward if K8s manifests don't block)

**Within Phase 3**:
- T3.1, T3.4, T3.6 are independent — parallel
- T3.3 depends on B-2 fix (Phase 1)
- T3.5 depends on C-1 (Phase 1)

---

## Summary

| Category | Count | Must-ship-before-prod |
|----------|-------|----------------------|
| Critical (existing plans) | 2 | Yes |
| High (existing plans) | 5 | Yes |
| Medium (existing plans) | 14 | No (incremental) |
| **Critical (new — B-series)** | **3** | **Yes** |
| **High (new — B-series)** | **5** | **Yes** |

**Total**: 29 issues. 10 must-ship-before-prod (Phase 1 + Phase 2 subset). 19 incremental improvements (Phase 3–5).

The project has strong fundamentals — determinism guarantees, dependency pinning, and operational documentation are all production-grade. These 8 newly-identified blocking issues (B-1 through B-8) are the gap between "well-built POC" and "safe to deploy."
