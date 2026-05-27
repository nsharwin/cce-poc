# Medium Findings — Implementation Plan

> Generated from production-readiness review on 2026-05-26.
> Covers 13 medium-severity findings (#8–#22, #19 already resolved in H-4).

---

## M-1: Add tenant-scoped audit filtering

**Finding #8** | Files: `src/cce_service/api/service.py`, `tests/service/test_api.py`, `src/cce_service/storage/repos.py`

### Problem

`list_audit()` at `service.py:230` returns all audit events globally — no per-tenant scoping. User in tenant A with `audit:read` scope can see audit events from tenant B.

### Fix

- Add `tenant` field to `AuditEvent` dataclass in `storage/models.py`
- Populate `tenant` when creating audit events from `principal.tenant`
- Add `since(ts_iso, tenant)` signature to `AuditRepo` protocol
- Filter `list_audit()` by `principal.tenant`

### Tasks

1. [ ] Add `tenant: str = "default"` field to `AuditEvent` dataclass
2. [ ] Update `AuditRepo.since()` protocol signature to accept `tenant` parameter
3. [ ] Update `InMemoryAuditRepo.since()` to filter by tenant
4. [ ] Update `PostgresAuditRepo.since()` to filter by tenant in query
5. [ ] Pass `principal.tenant` to all `audit_event()` calls in `service.py`
6. [ ] Pass `job.tenant` to audit calls in `consumer.py`
7. [ ] In `list_audit()`, filter by `principal.tenant` via repo
8. [ ] Add unit test: tenant A creates event → tenant B lists → not visible
9. [ ] Add unit test: tenant A creates event → tenant A lists → visible

### Acceptance criteria

- `list_audit()` returns only events for the requesting tenant
- Cross-tenant audit data is not visible (404 or empty list)

---

## M-2: Structured JSON logging

**Finding #9** | Files: `src/cce/cli.py`, `src/cce_service/api/service.py`, `src/cce_service/workers/consumer.py`, `src/cce_service/dispatch/firecracker.py`

### Problem

CLI uses `print(..., file=sys.stderr)` exclusively — no structured logging. Service modules use bare `logging.getLogger()` without formatters. Log lines are unstructured key=value format, not machine-parseable JSON.

### Fix

Add a `structlog`-style JSON formatter to the logging configuration, gated behind an env var so the POC dev image stays dependency-free.

### Tasks

1. [ ] Add `python-json-logger` to `cce-service` extras in `pyproject.toml`
2. [ ] Create `src/cce_service/logging_setup.py` with `setup_json_logging()` function
3. [ ] Configure JSON formatter that emits `{"timestamp": "...", "level": "...", "logger": "...", "message": "...", ...}`
4. [ ] Gate JSON logging behind `CCE_LOG_FORMAT=json` env var (default: plain text)
5. [ ] Call `setup_json_logging()` at API app startup and worker entrypoint
6. [ ] Add correlation ID support: extract/inject `x-request-id` header
7. [ ] Log job_id in all consumer/dispatch log lines via `extra=`
8. [ ] Add structured log for failed scoring runs in CLI `_print_error()` when JSON mode enabled

### Acceptance criteria

- `CCE_LOG_FORMAT=json` produces JSON lines on stderr
- Default (unset) produces plain text — no regression
- log lines include `logger`, `level`, `timestamp`, `message`
- Consumer logs include `job_id` field on every line during processing

---

## M-3: Correlation IDs across service boundaries

**Finding #10** | Files: `src/cce_service/api/app.py`, `src/cce_service/api/service.py`, `src/cce/cli.py`, `src/cce/otel.py`

### Problem

No trace_id, span_id, or request_id threaded through log lines. Cross-referencing API logs with worker logs requires timestamp correlation.

### Fix

Extract OTel trace_id/span_id from active span context and include them in structured log lines. For the CLI (no incoming request), use the record_hash as the correlation ID.

### Tasks

1. [ ] Add middleware to FastAPI app that extracts/injects `X-Request-Id` header
2. [ ] Store request_id in `contextvars.ContextVar` for thread-safe access
3. [ ] Add `trace_id` and `span_id` extraction from OTel context in logging formatter
4. [ ] Pass `job_id` to consumer log lines via `logging.LoggerAdapter`
5. [ ] In CLI, log `record_hash` as correlation_id on success
6. [ ] Update all `_logger.info/warning/error` calls to include correlation context

### Acceptance criteria

- Every API log line includes `request_id` and `trace_id` (when OTel is active)
- Consumer log lines include `job_id`
- CLI success path logs `record_hash` in structured output

---

## M-4: Postgres connection pool tuning

**Finding #11** | Files: `src/cce_service/storage/postgres.py`, `ops/staging/docker-compose.yml`

### Problem

Postgres engines use SQLAlchemy defaults: `pool_size=5`, `max_overflow=10`, no connect timeout, no `pool_recycle`. Production load should use tuned values and a shorter pool_recycle to handle connection drops behind load balancers.

### Fix

Parameterize pool settings via env vars with safe defaults.

### Tasks

1. [ ] Add `pool_size` and `max_overflow` parameters to `PostgresJobRepo.__init__` 
2. [ ] Add `connect_timeout` parameter (default: 10s)
3. [ ] Add `pool_recycle` parameter (default: 3600s / 1hr)
4. [ ] Read defaults from env: `CCE_PG_POOL_SIZE`, `CCE_PG_POOL_MAX_OVERFLOW`, `CCE_PG_POOL_RECYCLE`
5. [ ] Set `pool_pre_ping=True` (already done — verify)
6. [ ] Add `connect_args={"connect_timeout": 10}` to engine creation
7. [ ] Document settings in `.env.example`

### Acceptance criteria

- Pool size bounded by configured values
- Stale connections recycled after 1hr
- Connect timeout prevents hanging on DB unavailability

---

## M-5: ClickHouse adapter timeouts and write retry

**Finding #12** | Files: `src/cce_service/storage/clickhouse.py`

### Problem

`clickhouse_connect` client uses defaults — no explicit connect/read/write timeout. No retry on insert failure. (The core dispatch retry from H-1 doesn't cover ClickHouse write failures — those happen after the dispatch returns.)

### Fix

Configure client timeouts and wrap `upsert()` with our existing retry decorator.

### Tasks

1. [ ] Add `connect_timeout=10`, `send_receive_timeout=30` to `clickhouse_connect.get_client()` call
2. [ ] Sanitize env overrides: `CCE_CH_CONNECT_TIMEOUT`, `CCE_CH_SEND_RECEIVE_TIMEOUT`
3. [ ] Wrap `upsert()` body with `retry_on_transient_error(max_attempts=3, component="clickhouse")`
4. [ ] Add unit test for retry exhaustion on ClickHouse write failure
5. [ ] Update `.env.example` with ClickHouse timeout vars

### Acceptance criteria

- ClickHouse client has explicit connect and send/receive timeouts
- Transient write failures retry up to 3 times
- Write path does not block indefinitely

---

## M-6: FastAPI request body size limit

**Finding #13** | Files: `src/cce_service/api/app.py`

### Problem

No `maximum_request_size` or body-size middleware. An attacker can POST a multi-GB JSON body to `/v1/scores`.

### Fix

Add Starlette's `Request` body size limit via middleware. Accept 1 MiB (plenty for job payloads).

### Tasks

1. [ ] Add body-size middleware to FastAPI app: `max_content_length = 1 * 1024 * 1024` (1 MiB)
2. [ ] Catch `RequestEntityTooLarge` (HTTP 413) in exception handler
3. [ ] Add HTTP 413 test case in new `test_api_http.py` using `TestClient`

### Acceptance criteria

- POST body > 1 MiB returns 413
- Normal job payloads (< 1 KiB) unaffected

---

## M-7: Enforce HTTPS-only repo URLs

**Finding #14** | Files: `src/cce_service/api/service.py`

### Problem

`create_score()` accepts `http://` URLs. Only `https://` should be allowed in production (or configurable).

### Fix

Restrict to `https://` by default, with an env-var override for staging/localhost.

### Tasks

1. [ ] Change validation from `startswith(("https://", "http://"))` to `startswith("https://")`
2. [ ] Add `CCE_ALLOW_HTTP_REPOS=1` env var override for staging/dev
3. [ ] Read env var once at app startup, not per-request
4. [ ] Update BadRequest message to clarify https-only requirement
5. [ ] Update test to use `https://` URLs

### Acceptance criteria

- `http://` URLs rejected with 400 by default
- `CCE_ALLOW_HTTP_REPOS=1` restores http:// acceptance

---

## M-8: Docker service hardening (read-only rootfs + resource limits)

**Finding #15** | Files: `ops/staging/docker-compose.yml`, `ops/docker/Dockerfile`

### Problem

API and worker services in docker-compose lack `read_only: true` and resource limits (`deploy.resources.limits`).

### Fix

Add read-only rootfs with writable tmpfs mounts where needed.

### Tasks

1. [ ] Add `read_only: true` to `api` and `worker` services
2. [ ] Add `tmpfs: ["/tmp"]` for writable scratch space
3. [ ] Add `deploy.resources.limits`: memory=2G, cpus=2 for api; memory=4G, cpus=4 for worker
4. [ ] Verify services start and pass smoke test with read-only rootfs
5. [ ] Add `security_opt: ["no-new-privileges:true"]` to both services

### Acceptance criteria

- API and worker containers run with read-only root filesystems
- Smoke test passes with hardened compose config
- Containers cannot write outside `/tmp`

---

## M-9: HS256 production guardrail

**Finding #16** | Files: `src/cce_service/auth/jwt.py`, `src/cce_service/auth/__init__.py`

### Problem

`JwtVerifier` with HS256 (shared-secret) is intended for dev/test only. Nothing prevents it from being deployed to production — no runtime check or warning.

### Fix

Log a warning when HS256 verifier is constructed with `CCE_ENV != "development"`. Add a panic-mode env var to force rejection.

### Tasks

1. [ ] Add `_warn_hs256_in_prod()` helper that logs critical warning when `CCE_ENV` is not "development"
2. [ ] Add `CCE_REJECT_HS256=1` env var that causes `JwtVerifier.__init__` to raise `RuntimeError`
3. [ ] Document in `ops/staging/.env.example` and runbooks
4. [ ] Add test: `CCE_REJECT_HS256=1` makes `JwtVerifier(secret=...)` raise

### Acceptance criteria

- HS256 in non-dev env emits CRITICAL log line on startup
- `CCE_REJECT_HS256=1` prevents process start with HS256 verifier

---

## M-10: jailer.json digest injection mechanism

**Finding #17** | Files: `ops/firecracker/jailer.json`, `ops/docker/cce-entrypoint.py`

### Problem

`jailer.json` contains `REPLACE_AT_DEPLOY` placeholders for Firecracker binary, jailer, kernel, and rootfs digests. No injection mechanism exists — deployer must manually edit the file.

### Fix

Use `envsubst`-style variable substitution at container startup.

### Tasks

1. [ ] Replace `REPLACE_AT_DEPLOY` placeholders with `${FC_DIGEST}`, `${JAILER_DIGEST}`, `${KERNEL_DIGEST}`, `${ROOTFS_DIGEST}`
2. [ ] Add `envsubst` to production Docker image (or use a Python `string.Template` in entrypoint)
3. [ ] In `cce-entrypoint.py`, read `jailer.json`, substitute env vars, write resolved config to temp path
4. [ ] Validate all digests are non-empty after substitution (fail fast on missing env var)
5. [ ] Document required env vars in `.env.example`

### Acceptance criteria

- Containers start with `jailer.json` digests injected from env vars
- Missing env var causes clear startup error — no silent "REPLACE_AT_DEPLOY" in production
- Firecracker boot path unchanged after substitution

---

## M-11: N-1 storage compatibility test

**Finding #18** | Files: `tests/service/test_storage_compat.py` (TODO placeholder)

### Problem

The rollback strategy (`ops/rollback.md`) requires N-1 compatibility: previous image must read+write current schema for one release window. The test for this is a TODO placeholder.

### Fix

Implement the placeholder test using the in-memory repos.

### Tasks

1. [ ] Implement `test_storage_compat.py`:
   - Create records with current schema (including `tenant` field)
   - Simulate reading with "previous version" model (no `tenant` field)
   - Verify no data loss, default tenant populated
   - Verify no exception thrown on extra fields (forward compatibility)
2. [ ] Test both directions: old-schema write → new-schema read, new-schema write → old-schema read
3. [ ] Add to CI workflow as a required check

### Acceptance criteria

- Test exercises the N-1 compatibility contract from `ops/rollback.md`
- Previous-image schema can read records written by current-image schema
- CI blocks PRs that break the compatibility contract

---

## M-12: Production Kubernetes manifests

**Finding #20** | Files: `ops/k8s/` (new directory)

### Problem

Rollback docs reference `kubectl` commands against `cce` namespace, but no manifests exist in the repo.

### Fix

Create minimal production K8s manifests: Deployment, Service, ConfigMap, Secret template.

### Tasks

1. [ ] Create `ops/k8s/` directory structure
2. [ ] Create `api-deployment.yaml`: Deployment for FastAPI (2 replicas, resource limits, liveness/readiness probes)
3. [ ] Create `worker-deployment.yaml`: Deployment for worker (1 replica, resource limits)
4. [ ] Create `service.yaml`: ClusterIP Service for API
5. [ ] Create `configmap.yaml`: non-secret env vars from `.env.example`
6. [ ] Create `secret.yaml`: template with placeholder values (Postgres DSN, ClickHouse password, JWT secret)
7. [ ] Document apply order in `ops/k8s/README.md`

### Acceptance criteria

- `kubectl apply -f ops/k8s/` deploys a functional stack (modulo secrets)
- Manifests reference the same env vars as docker-compose
- Probes match docker-compose health checks

---

## M-13: SBOM generation in CI

**Finding #21** | Files: `.github/workflows/` (new or modified)

### Problem

No CycloneDX/SPDX SBOM generated in the build pipeline. Required for supply-chain compliance.

### Fix

Generate SBOM during CI build using `pip-audit` with CycloneDX output or `syft`.

### Tasks

1. [ ] Add SBOM generation step to CI workflow (after `pip install` / `uv sync`)
2. [ ] Use `uv export --format requirements-txt | cyclonedx-py` or `syft` on the built image
3. [ ] Output `sbom.cdx.json` as a workflow artifact
4. [ ] Fail CI if SBOM generation fails (soft-fail initially with a warning)
5. [ ] Attach SBOM to GitHub Releases (future)

### Acceptance criteria

- Every CI build produces an `sbom.cdx.json` artifact
- SBOM includes all Python packages with versions and licenses

---

## M-14: Docker HEALTHCHECK instruction

**Finding #22** | Files: `ops/docker/Dockerfile`

### Problem

Production Docker image has no `HEALTHCHECK` instruction. Docker/compose can't detect unhealthy containers at runtime.

### Fix

Add a `HEALTHCHECK` that pings the scoring entrypoint (CLI image) or the `/healthz` endpoint (service image).

### Tasks

1. [ ] For the service image: `HEALTHCHECK --interval=15s --timeout=5s CMD curl -f http://localhost:8080/healthz || exit 1`
2. [ ] For the CLI image: `HEALTHCHECK --interval=30s --timeout=5s CMD cce --version || exit 1`
3. [ ] Ensure `curl` is available in the service image (or use Python's `urllib`)
4. [ ] Add health check to docker-compose `api` and `worker` services

### Acceptance criteria

- `docker ps` shows healthy status for running containers
- Unhealthy containers are detected and restarted by orchestration
- Health check does not impact determinism (only in service/CLI startup path)

---

## Execution Order

| Phase | Tasks | Notes |
|-------|-------|-------|
| **Phase 5** | M-1 (audit tenant scoping), M-6 (body size limit), M-7 (https-only), M-9 (HS256 guardrail) | Simple, single-file fixes |
| **Phase 6** | M-4 (PG pool tuning), M-5 (CH timeouts), M-11 (N-1 compat test), M-14 (HEALTHCHECK) | Infra/config changes |
| **Phase 7** | M-2 (JSON logging), M-3 (correlation IDs) | Touches many files, pairs with M-2 |
| **Phase 8** | M-8 (Docker hardening), M-10 (jailer.json injection), M-12 (K8s manifests), M-13 (SBOM) | Ops/infra artifacts |

---

## Summary

| # | Finding | Severity | Effort | Risk |
|---|---------|----------|--------|------|
| M-1 | Audit tenant scoping | Medium | Small | Low |
| M-2 | JSON logging | Medium | Medium | Low |
| M-3 | Correlation IDs | Medium | Medium | Low |
| M-4 | PG pool tuning | Medium | Small | Low |
| M-5 | CH adapter timeouts | Medium | Small | Low |
| M-6 | Body size limit | Medium | Small | None |
| M-7 | HTTPS-only repo URLs | Medium | Small | Low (staging impact) |
| M-8 | Docker hardening | Medium | Medium | Medium (smoke test) |
| M-9 | HS256 guardrail | Medium | Small | None |
| M-10 | jailer.json injection | Medium | Medium | Medium (break boot) |
| M-11 | N-1 compat test | Medium | Medium | None |
| M-12 | K8s manifests | Medium | Large | None |
| M-13 | SBOM generation | Medium | Small | None |
| M-14 | Docker HEALTHCHECK | Medium | Small | None |

13 of 14 medium findings remain actionable (M-19 `.env.example` was resolved in H-4).
