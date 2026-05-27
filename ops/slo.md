# CCE Service SLOs

These SLOs are evaluated monthly. SLI definitions link directly to the
Prometheus expressions in `ops/observability/alerts/cce.rules.yaml`.

## Service availability

- **SLO**: 99.9% availability of `/v1/scores`, `/v1/scores/{id}`,
  `/v1/records/{hash}` over a rolling 30-day window.
- **SLI**: `1 - sum(rate(http_requests_total{job="cce-api",status=~"5.."}[30d])) / sum(rate(http_requests_total{job="cce-api"}[30d]))`
- **Error budget**: 43m 49s of unavailability per 30 days.
- **Page rule**: `CCEApi5xxRateHigh` — 5xx > 1% for 10 min.

## Score latency

- **SLO**: p95 wall-clock of `POST /v1/scores` → `GET /v1/scores/{id}.status=succeeded`
  is ≤ 90 s for repositories ≤ 100 000 LoC.
- **SLI**: `histogram_quantile(0.95, sum by (le) (rate(cce_score_duration_seconds_bucket{stage="total"}[10m])))`
- **Perf gate**: `tests/perf/test_100k_loc.py` enforces wall ≤ 90 s and
  RSS ≤ 2 GiB on every PR via `.github/workflows/perf-gate.yml`
  (POC-GATE-8).
- **Page rule**: `CCEScoreLatencyP95High` — p95 > 90 s for 15 min.

## Record retrieval latency

- **SLO**: p95 of `GET /v1/records/{record_hash}` ≤ 200 ms.
- **SLI**: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="cce-api",route="/v1/records"}[10m])))`
- **Ticket rule**: `CCERecordReadLatencyP95High` — p95 > 200 ms for 10 min.

## Determinism

- **SLO**: zero cross-runner record-hash mismatches per 7-day window.
- **SLI**: `max_over_time(cce_record_hash_mismatch_total[7d])`
- **Page rule**: `CCERecordHashMismatch` — any non-zero value in last 24 h.
- **Backing gate**: `.github/workflows/nightly-stability.yml`
  + `ops/nightly-streak.json` enforce a 7-day green streak (POC-GATE-3).

## Worker isolation

- **SLO**: every successful score executed inside a Firecracker microVM
  with no network interface (PREQ-X-4 / REQ-X-5).
- **SLI**: `cce_firecracker_boot_failures_total` must remain at 0 over a
  24-hour rolling window; failed dispatches are categorised in
  `cce_job_failures_total{reason="dispatch"}`.
- **Page rule**: `CCEFirecrackerBootFailures` — any boot failure for 5 min.
