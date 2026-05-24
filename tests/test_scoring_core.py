from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import ROUND_HALF_EVEN, Decimal, getcontext

from cce.canonical import canonical_json_bytes
from cce.scoring import build_score_record, normalise_metric, verify_record_hash
from cce.spec import spec_from_mapping
from tests.sample_data import COMMIT_SHA, sample_raw_metrics, sample_spec_mapping


def test_piecewise_linear_normalisation_uses_decimal_half_even() -> None:
    spec = spec_from_mapping(sample_spec_mapping())

    result = normalise_metric(
        Decimal("35"),
        spec.normalisation["cyclomatic"],
        spec.decimal_places,
    )

    assert getcontext().prec == 28
    assert getcontext().rounding == ROUND_HALF_EVEN
    assert result == Decimal("0.6250")


def test_score_record_hash_matches_preq_s_4_byte_concatenation() -> None:
    spec = spec_from_mapping(sample_spec_mapping())
    record = build_score_record(
        spec=spec,
        raw_metrics=sample_raw_metrics(),
        repo="fixture",
        mode="repo",
        commit_sha=COMMIT_SHA,
        computed_at="2026-05-24T00:00:00Z",
    )

    digest = hashlib.sha256()
    digest.update(record["spec_hash"].encode("utf-8"))
    digest.update(record["commit_sha"].encode("utf-8"))
    digest.update(canonical_json_bytes(record["metrics"]))
    digest.update(canonical_json_bytes(record["tool_digests"]))

    assert record["metrics"]["cyclomatic"] == {"raw": "35", "normalised": "0.6250"}
    assert record["metrics"]["file_length"] == {"raw": "450", "normalised": "0.3750"}
    assert record["score"] == "0.4312"
    assert record["record_hash"] == f"sha256:{digest.hexdigest()}"


def test_computed_at_is_excluded_from_record_hash() -> None:
    spec = spec_from_mapping(sample_spec_mapping())

    first = build_score_record(
        spec=spec,
        raw_metrics=sample_raw_metrics(),
        repo="fixture",
        mode="repo",
        commit_sha=COMMIT_SHA,
        computed_at="2026-05-24T00:00:00Z",
    )
    second = build_score_record(
        spec=spec,
        raw_metrics=sample_raw_metrics(),
        repo="fixture",
        mode="repo",
        commit_sha=COMMIT_SHA,
        computed_at="2026-05-25T00:00:00Z",
    )

    assert first["computed_at"] != second["computed_at"]
    assert first["record_hash"] == second["record_hash"]


def test_verify_record_hash_rejects_metric_mutation() -> None:
    spec = spec_from_mapping(sample_spec_mapping())
    record = build_score_record(
        spec=spec,
        raw_metrics=sample_raw_metrics(),
        repo="fixture",
        mode="repo",
        commit_sha=COMMIT_SHA,
        computed_at="2026-05-24T00:00:00Z",
    )

    mutated = deepcopy(record)
    mutated["metrics"]["cyclomatic"]["raw"] = "36"

    assert verify_record_hash(record)
    assert not verify_record_hash(mutated)
