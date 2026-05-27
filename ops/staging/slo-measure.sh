#!/usr/bin/env bash
# Run the smoke flow N times against staging, compute p95 latencies,
# and write a "Measured (staging, <ISO date>)" block into ops/slo.md.
#
# Usage:
#   ITERATIONS=200 ops/staging/slo-measure.sh
#
# Output goes to stdout and is appended to ops/slo.md.

set -euo pipefail

ITERATIONS="${ITERATIONS:-200}"
API="${CCE_API_URL:-http://localhost:${CCE_API_PORT:-8080}}"
ENV_FILE="${ENV_FILE:-ops/staging/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC2046
  set -a; source "${ENV_FILE}"; set +a
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

echo "Running ${ITERATIONS} smoke iterations against ${API}..." >&2

for i in $(seq 1 "${ITERATIONS}"); do
  t0=$(python3 -c "import time;print(time.perf_counter())")
  output=$(ops/staging/smoke.sh 2>/dev/null | tail -n 1)
  t1=$(python3 -c "import time;print(time.perf_counter())")
  e2e_ms=$(python3 -c "print(int((${t1} - ${t0}) * 1000))")
  hash=$(echo "${output}" | sed 's/^SMOKE OK record_hash=//')

  t2=$(python3 -c "import time;print(time.perf_counter())")
  curl -fsS "${API}/v1/records/${hash}" > /dev/null
  t3=$(python3 -c "import time;print(time.perf_counter())")
  read_ms=$(python3 -c "print(int((${t3} - ${t2}) * 1000))")

  printf '%s %s\n' "${e2e_ms}" "${read_ms}" >> "${TMP}/samples.txt"
  printf '\r  iteration %d/%d' "${i}" "${ITERATIONS}" >&2
done
echo >&2

python3 - <<PY > /tmp/slo-fragment.md
import statistics, datetime
e2e, reads = [], []
with open("${TMP}/samples.txt") as f:
    for line in f:
        a, b = line.split()
        e2e.append(int(a)); reads.append(int(b))
def pct(xs, p):
    xs = sorted(xs)
    k = max(0, min(len(xs)-1, int(round((p/100)*(len(xs)-1)))))
    return xs[k]
now = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
print(f"## Measured (staging, {now})")
print()
print(f"- Samples: {len(e2e)}")
print(f"- POST /v1/scores → succeeded (end-to-end): p50={pct(e2e,50)} ms, p95={pct(e2e,95)} ms, p99={pct(e2e,99)} ms")
print(f"- GET /v1/records/{{record_hash}}:             p50={pct(reads,50)} ms, p95={pct(reads,95)} ms, p99={pct(reads,99)} ms")
PY

echo "--- /tmp/slo-fragment.md ---"
cat /tmp/slo-fragment.md
echo "--- /tmp/slo-fragment.md ---"
echo >> ops/slo.md
cat /tmp/slo-fragment.md >> ops/slo.md
echo "appended Measured block to ops/slo.md"
