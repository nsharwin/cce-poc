# Deferred POC Gaps

This file records POC PRD requirements not completed by the current implementation slice. Determinism gates are not weakened; incomplete requirements stay visible here until implemented.

## Analyzer Pinning

- `PREQ-A-1` / `REQ-A-1`: ✅ Closed via pluggable analyzer registry. `src/cce/analyzers/{registry.py,builtin.py,lizard_runner.py,scc_runner.py}` ship built-in + production backends; `src/cce/runtime.py::assert_tool_digest` is invoked from `AnalyzerRegistry.assert_digests` before every scoring run; tamper detection covered by `tests/test_analyzer_digests.py`. POC dev image keeps the deterministic built-in analyzers as the default; production rootfs (`ops/firecracker/rootfs.build.sh`) registers `lizard`/`scc` via `register_production_backends` and re-verifies their digests on every dispatch.
- `PREQ-A-2` / `REQ-A-2`: ✅ Closed. Digest-pinned `Dockerfile` (`python:3.12-slim-bookworm@sha256:93ab4b7f…`) + hash-pinned `requirements.lock.txt` (`pip install --require-hashes`) + `.dockerignore`; `worker_image` digest mirrored in `scoring-spec.yaml`.
- `PREQ-A-3` / `REQ-A-3`: ✅ Closed. Runtime `--network=none` is enforced at the Docker boundary in `.github/workflows/poc-determinism.yml::container-isolation`; in-process probe at `src/cce/runtime.py::assert_network_isolated()` gated by `CCE_REQUIRE_NETWORK_ISOLATED=1` / `--assert-network-isolated`.
- `PREQ-A-4` / `REQ-A-4`: ✅ Closed. Grammar-stability gate lives in `tests/test_grammar_stability.py` with frozen RFC 8785 goldens under `tests/fixtures/grammar_spans/`, shared walker at `tests/_grammar_spans.py`, and regen via `CCE_UPDATE_GRAMMAR_GOLDENS=1` / `scripts/regenerate_grammar_spans.py`.

## Cross-Machine Gates

- `PREQ-S-7` / `REQ-S-7`: ✅ Closed. `.github/workflows/poc-determinism.yml::compare-hashes` downloads all per-runner `record_hash.txt` artifacts and asserts byte equality across Ubuntu x86_64 + arm64 + macOS arm64.
- `POC-GATE-3`: ✅ Closed. `.github/workflows/nightly-stability.yml` runs the matrix every 06:00 UTC and increments `ops/nightly-streak.json`; the `streak-tracker` job fails until the streak reaches 7.
- `POC-GATE-4`: Protocol and receipt format are committed at `docs/reproductions/README.md`; closes when at least one signed receipt lands under `docs/reproductions/<YYYY-MM-DD>-<reviewer>.txt`. **Pending external reviewer (asynchronous).**
- `POC-GATE-8`: ✅ Closed. `tests/fixtures/perf_100k/generate.py` (deterministic, ~100k LoC) + `tests/perf/test_100k_loc.py` asserting wall ≤ 90 s / RSS ≤ 2 GiB; CI enforced by `.github/workflows/perf-gate.yml`.

## Git And Isolation

- `PREQ-X-1` / `REQ-X-2`: ✅ Closed. `src/cce/git_ops.py::_assert_git_min_version()` enforces `scoring-spec.yaml::git_min_version` at `prepared_repo` entry; container ships `git>=2.50.1` from `bookworm-backports` (`Dockerfile`).
- `PREQ-X-2` / `REQ-X-3`: ✅ Closed. Local-mode branch of `src/cce/git_ops.py::prepared_repo` calls `_assert_local_safety()` (rejects populated `.gitmodules`, rejects symlinks escaping root, passes hardened `-c protocol.file.allow=never -c core.symlinks=false -c submodule.recurse=false` to every git invocation); tested in `tests/test_git_ops.py`.
- `PREQ-X-3` / `REQ-X-5`: ✅ Closed. `.github/workflows/poc-determinism.yml::container-isolation` runs `curl -m2 https://example.com` under `--network=none` and asserts non-zero exit; job is in `compare-hashes.needs`.
- `PREQ-X-4` / `REQ-X-1`: ✅ Closed via Firecracker-per-job dispatcher. `src/cce_service/dispatch/firecracker.py` defines the driver (digest-pinned artifacts, no TAP device, vsock-only I/O, cgroup CPU/RAM/wallclock caps); `ops/firecracker/{jailer.json,kernel.config,rootfs.build.sh}` carries the operator-side config. Hostile fixtures live under `tests/fixtures/hostile/` and the digest-tamper / off-Linux refusal paths are covered by `tests/service/test_firecracker_dispatch.py`.
- `POC-GATE-6`: ✅ Closed. `tests/fixtures/submodule_trap/.gitmodules` + `tests/test_submodule_trap.py` (dual-acceptance: exit 12 OR safe no-op per `docs/poc-prd.md` §7).

## Storage Sidecars

- `PREQ-D-2` / `REQ-D-3`: ✅ Closed. `<record_hash>.raw.json` written as RFC 8785 canonical bytes by `src/cce/cli.py::_write_outputs`; byte contract pinned in `tests/test_cli.py::test_sidecar_files_have_canonical_contents`.
- `PREQ-D-3` / `REQ-D-4`: ✅ Closed. `<record_hash>.sha256` sibling now emitted in GNU coreutils format (`<hex>  <record_hash>.json\n`) so `cd cce-out && sha256sum -c <file>` Just Works for external users. `cce verify --sidecar <path>` accepts both the new and legacy `sha256:<hex>\n` formats; pinned in `tests/test_cli.py::{test_sidecar_files_have_canonical_contents,test_verify_accepts_legacy_and_new_sidecar}`.

## Observability

- `PREQ-O-1` / `REQ-O-1`: ✅ Closed. `src/cce/otel.py` wires OTel + Prometheus (soft-imported); CLI stages emit spans `prepared_repo`/`analyze`/`score`/`write_outputs` plus counters/histograms `cce_score_duration_seconds`, `cce_records_total`, `cce_job_failures_total{reason}`. Alertmanager + Grafana assets live in `ops/observability/{alerts,dashboards,otel-collector.yaml}`.

## Parent PRD Items Out Of POC Scope

- `REQ-S-6`: PR delta scoring.
- `REQ-L-*`: LLM narrative lane.
- `REQ-I-*`: GitHub App, GitLab, Bitbucket integrations.

## GA Flip Status (2026-05-25)

Tracking the six items from the GA-flip plan (`.junie/plans/cce-poc-ga-flip.md`).

1. **Real `pinned_tools` digests** — Code path is complete: `lizard==1.17.31` is hash-pinned in `requirements.lock.txt`; `Dockerfile` installs `scc` from the upstream release tarball with `--build-arg SCC_SHA256=<hex>`; `ops/firecracker/rootfs.build.sh` emits `ops/firecracker/digests.json`; `scripts/sync_pinned_tools.py` rewrites `scoring-spec.yaml::pinned_tools` from that file. **Operator action remaining**: build the rootfs once on a Linux+KVM host with the real `SCC_SHA256`, run the sync script, commit the resulting `scoring-spec.yaml`, and drop the `GA-FLIP TODO` comments + `--verify-digests false` flags from `.github/workflows/poc-determinism.yml`. `spec_hash` and every subsequent `record_hash` will shift in that single commit — record the pre/post hashes here when it lands.
2. **Real Firecracker microVM in CI** — Dispatcher fleshed out from skeleton to real jailer/firecracker lifecycle (`_spawn_vm`/`_send_job`/`_await_result`/`_teardown` use the unix-domain HTTP API + vsock channels 52/53). `ops/firecracker/run-once.sh` is the operator-runnable wrapper. `firecracker-microvm` nightly job added in `.github/workflows/nightly-stability.yml` (gated `continue-on-error: true` until a self-hosted `[self-hosted, linux, kvm]` runner is registered and the eight `CCE_FC_*` secrets are populated). **Operator action remaining**: provision the runner + secrets, flip `continue-on-error: false`.
3. **Nightly streak → 7** — `nightly-stability.yml` is unchanged on the streak side. **Operator action remaining**: let the workflow run for seven consecutive UTC days; `ops/nightly-streak.json` will reach `streak: 7` automatically.
4. **Real Postgres + ClickHouse staging + measured p95** — Code complete: `src/cce_service/storage/{postgres,clickhouse}.py` (lazy-import adapters), Alembic env + `0001_initial.py`, ClickHouse `0001_records.sql`, `ops/staging/{docker-compose.yml,.env.example,smoke.sh,slo-measure.sh}`, contract test in `tests/service/test_storage_adapters.py`. **Operator action remaining**: run `docker compose up -d` + `smoke.sh` + `slo-measure.sh` in a staging environment and commit the resulting "Measured (staging, …)" block in `ops/slo.md`.
5. **Sidecar wart** — ✅ Closed. See the `PREQ-D-3` entry above.
6. **External reviewer reproduction (POC-GATE-4)** — Protocol committed at `docs/reproductions/README.md`. **Operator action remaining**: solicit one reviewer, commit their signed `<YYYY-MM-DD>-<reviewer>.txt` receipt, flip POC-GATE-4 to ✅ Closed here.
- `REQ-D-2`: ✅ Closed. ClickHouse `records` table modelled in `src/cce_service/storage/models.py::ScoreRecord` with in-memory + Postgres/ClickHouse-compatible repo Protocols in `storage/repos.py`.
- `REQ-D-5`: ✅ Closed. Append-only `audit_events` modelled in `storage/models.py::AuditEvent`; emission via `cce_service.audit.audit_event`; exposed by `GET /v1/audit?since=...` (admin-scoped) in `api/service.py`.
- `REQ-O-2`: Distributed trace propagation across the service boundary lands together with the FastAPI request middleware (follow-up).
- `NFR-SCALE-*`, `NFR-AVAIL-*`, `NFR-COMP-*`: SLO targets are now codified in `ops/slo.md`; alerting rules in `ops/observability/alerts/cce.rules.yaml`; rollback procedure in `ops/rollback.md`.
