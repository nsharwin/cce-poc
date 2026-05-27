# Runbook: `CCEApi5xxRateHigh`

**Symptom**: API 5xx rate > 1% for 10 minutes.
**Pager severity**: page

## Detect
- Alertmanager fires `CCEApi5xxRateHigh`.
- Grafana panel "API request rate by status" shows 5xx spike on
  `cce-overview` dashboard.

## Diagnose
1. `kubectl -n cce logs -l app=cce-api --tail=200 --since=15m | grep -E 'ERROR|5[0-9]{2}'`
2. Check `cce_job_failures_total{reason=...}` breakdown — if `reason=spec`
   or `reason=digest` spikes, a bad spec or tampered binary was deployed.
3. Check Postgres health: `pg_isready -h $PGHOST` and replica lag.

## Mitigate
- **Bad deploy**: follow `ops/rollback.md`.
- **DB outage**: scale API to 503-only mode by setting
  `CCE_READONLY_MODE=1`; the API will return `503 Retry-After: 30`
  instead of 5xx.
- **Single bad tenant**: blacklist via `kubectl -n cce patch configmap
  cce-rate-limits ...`.

## Escalate
- 30 min unresolved → page on-call SRE lead.
- 60 min unresolved → declare SEV-2, open incident channel.
