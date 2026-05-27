# Rollback Procedure

Goal: revert a bad release (API or worker image) to the previous known-good
build **in ≤ 10 minutes**, without losing in-flight scoring jobs and
without breaking ``record_hash`` reproducibility.

## Deploy model: blue/green by image digest

- API + workers are deployed as two parallel ``blue`` and ``green``
  stacks behind a weighted load balancer.
- Every image is pinned by ``sha256@digest`` in the deployment manifest;
  tags (``cce-api:v1.4.2``) are humans-only labels.
- Promotion is a single LB weight flip from ``blue=0/green=100`` to
  ``blue=100/green=0`` (or vice versa).

## Schema migrations

- **Forward-only**, but every release must be **N-1 compatible**: the
  previous image must read+write the new schema for the duration of one
  release window (default 7 days).
- This contract is enforced by `tests/service/test_storage_compat.py`
  (TODO — placeholder pending Step 4 follow-up).
- ClickHouse `records` table changes are append-only columns with
  ``DEFAULT`` clauses; never drop or rename within a release window.

## Step-by-step rollback

1. **Detect**: page from `CCEApi5xxRateHigh`, `CCEScoreLatencyP95High`,
   or operator-triggered.
2. **Freeze writes** (optional, for data-integrity incidents only):
   ```
   kubectl scale deploy/cce-worker --replicas=0
   ```
3. **Flip LB weight** back to the previous stack:
   ```
   kubectl -n cce patch service/cce-api \
     --type=merge -p '{"spec":{"selector":{"stack":"blue"}}}'
   ```
4. **Verify** with the smoke endpoint:
   ```
   curl -fsS https://cce.example.com/healthz
   curl -fsS -H "Authorization: Bearer $SMOKE_TOKEN" \
     https://cce.example.com/v1/records/sha256:<known-good-hash>
   ```
5. **Re-enable workers** of the rolled-back stack:
   ```
   kubectl scale deploy/cce-worker-blue --replicas=5
   ```
6. **Drain green stack** workers without dropping in-flight jobs:
   ```
   kubectl -n cce annotate deploy/cce-worker-green cce.drain=true
   kubectl wait --for=jsonpath='{.status.observedJobs}'=0 \
     deploy/cce-worker-green --timeout=10m
   ```
7. **Post-incident**:
   - Capture the failing image digest in `ops/incidents/<date>.md`.
   - Open an issue with the failing PR linked.
   - Rerun `nightly-stability.yml` once before re-promoting.

## Determinism guarantee under rollback

`record_hash` is a pure function of `(spec_hash, commit_sha, metrics,
tool_digests)`. As long as the rolled-back image:

- pins the same `scoring-spec.yaml::spec_hash`, and
- ships analyzer binaries with the same `tool_digests`,

scoring the same `(repo_url, commit_sha)` produces the same
`record_hash` byte-for-byte. The matrix-hash CI job is the canary; if it
trips after a rollback, the rolled-back image itself is divergent and
must be quarantined.
