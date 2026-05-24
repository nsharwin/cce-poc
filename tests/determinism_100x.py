from __future__ import annotations

from cce.scoring import build_score_record
from cce.spec import spec_from_mapping
from tests.sample_data import COMMIT_SHA, sample_raw_metrics, sample_spec_mapping


def test_determinism_100x_produces_one_unique_record_hash() -> None:
    spec = spec_from_mapping(sample_spec_mapping())

    hashes = {
        build_score_record(
            spec=spec,
            raw_metrics=sample_raw_metrics(),
            repo="fixture",
            mode="repo",
            commit_sha=COMMIT_SHA,
            computed_at=f"2026-05-24T00:00:{index:02d}Z",
        )["record_hash"]
        for index in range(100)
    }

    assert len(hashes) == 1
