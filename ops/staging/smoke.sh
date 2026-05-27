#!/usr/bin/env bash
# Staging smoke: Alembic upgrade, ClickHouse DDL, three-endpoint round-trip.
#
# Requires: the `ops/staging/docker-compose.yml` stack already running
# and `ops/staging/.env` populated. Re-runnable; idempotent on the DB side.
#
# Usage:
#   ops/staging/smoke.sh
#
# Emits a single line on success:   SMOKE OK record_hash=<sha256:…>

set -euo pipefail

ENV_FILE="${ENV_FILE:-ops/staging/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC2046
  set -a; source "${ENV_FILE}"; set +a
fi

API="${CCE_API_URL:-http://localhost:${CCE_API_PORT:-8080}}"
PG_DSN="${CCE_POSTGRES_DSN:-postgresql+psycopg://${CCE_PG_USER:-cce}:${CCE_PG_PASSWORD:-cce}@localhost:${CCE_PG_PORT:-5432}/${CCE_PG_DB:-cce}}"
CH_URL="${CCE_CLICKHOUSE_URL:-http://localhost:${CCE_CH_HTTP_PORT:-8123}}"

echo ">>> applying Alembic migrations against ${PG_DSN}"
CCE_POSTGRES_DSN="${PG_DSN}" uv run alembic upgrade head

echo ">>> applying ClickHouse DDL against ${CH_URL}"
curl -fsS -X POST "${CH_URL}" \
  --data-binary @src/cce_service/migrations/clickhouse/0001_records.sql > /dev/null

echo ">>> POST /v1/scores"
JOB_PAYLOAD='{"repo_url":"https://github.com/cce/fixture-simple_python.git","spec_ref":"./scoring-spec.yaml","tenant":"default"}'
JOB_ID=$(curl -fsS -X POST "${API}/v1/scores" \
  -H "Content-Type: application/json" \
  -d "${JOB_PAYLOAD}" | python3 -c "import json,sys;print(json.load(sys.stdin)['job_id'])")
echo "  job_id=${JOB_ID}"

echo ">>> GET /v1/scores/${JOB_ID} (poll to succeeded)"
deadline=$(( $(date +%s) + 60 ))
RECORD_HASH=""
while [[ "$(date +%s)" -lt "${deadline}" ]]; do
  body=$(curl -fsS "${API}/v1/scores/${JOB_ID}")
  status=$(echo "${body}" | python3 -c "import json,sys;print(json.load(sys.stdin).get('status',''))")
  if [[ "${status}" == "succeeded" ]]; then
    RECORD_HASH=$(echo "${body}" | python3 -c "import json,sys;print(json.load(sys.stdin)['record_hash'])")
    break
  fi
  if [[ "${status}" == "failed" ]]; then
    echo "FAIL: job failed: ${body}" >&2; exit 1
  fi
  sleep 1
done
if [[ -z "${RECORD_HASH}" ]]; then
  echo "FAIL: job did not reach succeeded within 60s" >&2; exit 1
fi

echo ">>> GET /v1/records/${RECORD_HASH}"
curl -fsS "${API}/v1/records/${RECORD_HASH}" > /dev/null

echo "SMOKE OK record_hash=${RECORD_HASH}"
