# Runbook: `CCEScoreLatencyP95High` / `CCEJobFailureRateHigh` / `CCEQueueDepthHigh`

**Symptom**: scoring jobs are slow, queue is backing up, or workers are
crashing.
**Pager severity**: page (latency, failures) / ticket (queue depth).

## Detect
- Page from one of the three alerts above.
- Grafana "score duration p95" or "Queue depth" panel.

## Diagnose
1. List worker pods and recent restarts:
   `kubectl -n cce get pods -l app=cce-worker -o wide`
   `kubectl -n cce describe pod <worker-pod> | grep -A3 'State:'`
2. Inspect failure-reason distribution:
   `sum by (reason) (rate(cce_job_failures_total[10m]))`
3. Check Firecracker boot rate:
   `rate(cce_firecracker_boot_failures_total[5m])` — if > 0, see
   `firecracker-boot-fail.md`.
4. Check Redis queue depth and consumer lag:
   `redis-cli xinfo stream cce:jobs` → look at `lag`.

## Mitigate
- **Stuck workers**: scale up replicas
  `kubectl -n cce scale deploy/cce-worker --replicas=+5`.
- **Hot repo / abusive tenant**: tighten rate-limit for that tenant
  (`cce-rate-limits` ConfigMap).
- **Bad analyzer**: roll back per `ops/rollback.md`.
- **In-flight job hangs > wallclock cap**: the jailer kills the VM at
  120 s; if jobs hang longer, restart workers (`kubectl rollout restart
  deploy/cce-worker`).

## Escalate
- 30 min unresolved or queue depth still rising → page worker on-call.
- Any sustained `reason=unexpected` failures → engage core team.
