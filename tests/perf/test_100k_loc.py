"""POC-GATE-8: 100k LoC scoring must finish under the production SLO.

Budgets (per ``ops/slo.md``):
- wall-clock ≤ 90 s end-to-end (analyze + score + write)
- max RSS ≤ 2 GB

The test is gated behind ``CCE_RUN_PERF=1`` so it does not run on every
local invocation; the dedicated ``perf-gate.yml`` workflow exports the
flag in CI. On macOS, ``ru_maxrss`` is reported in bytes; on Linux it is
KiB — we normalise both to bytes.
"""

from __future__ import annotations

import os
import resource
import sys
import time
from pathlib import Path

import pytest

from cce.analyzer import analyse_repo
from tests.fixtures.perf_100k.generate import build_fixture, estimated_loc

WALL_BUDGET_S = 90.0
RSS_BUDGET_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def _maxrss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS: bytes; Linux: kilobytes. Heuristic via sys.platform.
    if sys.platform == "darwin":
        return int(rss)
    return int(rss) * 1024


@pytest.mark.skipif(
    os.environ.get("CCE_RUN_PERF") != "1",
    reason="set CCE_RUN_PERF=1 to enable POC-GATE-8 perf gate",
)
def test_100k_loc_within_slo(tmp_path: Path) -> None:
    fixture_root = tmp_path / "perf_100k"
    build_fixture(fixture_root)
    assert estimated_loc() >= 100_000, "fixture must be ≥100 000 LoC"

    rss_before = _maxrss_bytes()
    started = time.perf_counter()
    raw_metrics, raw_payload = analyse_repo(fixture_root)
    wall = time.perf_counter() - started
    rss_after = _maxrss_bytes()

    assert raw_payload["files"], "perf fixture produced no files"
    assert wall <= WALL_BUDGET_S, (
        f"POC-GATE-8: analyse_repo took {wall:.1f}s, budget is {WALL_BUDGET_S}s"
    )
    assert rss_after <= RSS_BUDGET_BYTES, (
        f"POC-GATE-8: maxrss {rss_after / 1e9:.2f} GB exceeded {RSS_BUDGET_BYTES / 1e9:.2f} GB "
        f"(delta {(rss_after - rss_before) / 1e6:.1f} MB)"
    )
