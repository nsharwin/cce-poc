-- ClickHouse bootstrap DDL for the CCE service (REQ-D-2).
--
-- ClickHouse migrations are not Alembic-native; this file is applied
-- by `ops/staging/smoke.sh` (and a manual `clickhouse-client < file`)
-- and is idempotent — re-running on an existing schema is a no-op.
--
-- The records table is keyed by record_hash so re-inserting the same
-- record (e.g. on worker retry) collapses to one row after the next
-- background merge. Use SELECT ... FINAL for read-after-write parity.

CREATE DATABASE IF NOT EXISTS cce;

CREATE TABLE IF NOT EXISTS cce.records
(
    record_hash        String,
    commit_sha         String,
    repo_url           String,
    spec_hash          String,
    score              String,
    metrics_json       String,
    tool_digests_json  String,
    tenant             String DEFAULT 'default',
    created_at         DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (record_hash)
SETTINGS index_granularity = 8192;

-- Add tenant column to existing records table (N-1 compatible, forward-only).
-- Idempotent: ALTER TABLE ADD COLUMN is a no-op if the column already exists.
ALTER TABLE cce.records ADD COLUMN IF NOT EXISTS tenant String DEFAULT 'default';
