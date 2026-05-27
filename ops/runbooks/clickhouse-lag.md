# Runbook: `CCERecordReadLatencyP95High`

**Symptom**: `GET /v1/records/{record_hash}` p95 > 200 ms.
**Pager severity**: ticket.

## Detect
- Alert `CCERecordReadLatencyP95High`.
- Grafana "Record GET p95" panel.

## Diagnose
1. ClickHouse health:
   `clickhouse-client --query "SELECT * FROM system.replicas WHERE is_readonly"`
2. Replica lag:
   `clickhouse-client --query "SELECT absolute_delay FROM system.replicas WHERE table='records'"`
3. Inspect slow-query log for the `records` table.
4. Check if a recent migration added an `ALTER TABLE ... ADD COLUMN`
   that hasn't completed.

## Mitigate
- **Stale replica**: route reads to the leader by setting
  `CCE_CLICKHOUSE_PREFER_LEADER=1` on the API deploy and rolling.
- **Hot record**: enable the in-process LRU cache by setting
  `CCE_RECORDS_CACHE_BYTES=64MiB`.
- **Schema migration in flight**: wait for completion; do not retry —
  the table engine is `ReplacingMergeTree`, point reads stay correct.

## Escalate
- 30 min unresolved → page DB on-call.
- If `absolute_delay > 300 s`, declare SEV-3 and disable writes
  via worker scale-down to let replicas catch up.
