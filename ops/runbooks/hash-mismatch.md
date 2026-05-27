# Runbook: `CCERecordHashMismatch`

**Symptom**: cross-runner or cross-rebuild `record_hash` divergence
detected.
**Pager severity**: page (correctness incident).

This is a determinism breach — **never silence this alert**.

## Detect
- Alert `CCERecordHashMismatch` (any non-zero in 24 h window).
- `.github/workflows/poc-determinism.yml::compare-hashes` job fails.
- `.github/workflows/nightly-stability.yml` resets the streak in
  `ops/nightly-streak.json`.

## Diagnose
1. Fetch the divergent artifacts:
   ```
   gh run download <run-id> --pattern 'record-hash-*'
   ```
2. Pairwise-diff:
   ```
   for f in record-hash-*/record_hash.txt; do echo "$f $(cat $f)"; done
   ```
3. For the diverging runner, also fetch `.raw.json` and diff the
   `summary` block — this isolates analyzer-output divergence vs.
   pure scoring divergence.
4. If `tool_digests` differ between artifacts, an analyzer binary on one
   runner is wrong-arch or tampered.
5. If `metrics` differ but `tool_digests` match, the analyzer is
   non-deterministic — a regression in `lizard`/`scc` or `tree-sitter`.

## Mitigate
- **Immediate**: freeze deploys
  (`kubectl -n cce annotate deploy/cce-worker cce.frozen=true`)
  so no new records are written until root cause is known.
- **Quarantine** the divergent record by setting
  `quarantined=1` on its ClickHouse row.
- **Roll back** to the last green analyzer image per `ops/rollback.md`.
- **Reissue** scoring for affected `(repo, commit)` pairs after rollback
  — they will produce the deterministic hash again.

## Escalate
- Always page determinism core team.
- File a SEV-1 if a published record is affected; customers may have
  cached the bad hash.
