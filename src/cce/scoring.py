from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import ROUND_HALF_EVEN, Decimal, getcontext, localcontext
from typing import Any

from cce.canonical import canonical_json_bytes
from cce.spec import METRIC_NAMES, NormalisationRule, ScoringSpec

getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ScoringError(ValueError):
    pass


def normalise_metric(
    value: Decimal,
    rule: NormalisationRule,
    decimal_places: int,
) -> Decimal:
    with _decimal_context():
        quant = _quantizer(decimal_places)
        cuts = rule.cuts
        normalised = rule.normalised

        if value <= cuts[0]:
            return normalised[0].quantize(quant)

        for index in range(1, len(cuts)):
            upper_cut = cuts[index]
            if value <= upper_cut:
                lower_cut = cuts[index - 1]
                lower_norm = normalised[index - 1]
                upper_norm = normalised[index]
                span = upper_cut - lower_cut
                position = (value - lower_cut) / span
                result = lower_norm + (position * (upper_norm - lower_norm))
                return result.quantize(quant)

        return normalised[-1].quantize(quant)


def score_metrics(
    spec: ScoringSpec,
    raw_metrics: dict[str, str | int | Decimal],
) -> tuple[dict[str, dict[str, str]], Decimal]:
    with _decimal_context():
        quant = _quantizer(spec.decimal_places)
        metric_records: dict[str, dict[str, str]] = {}
        score = Decimal("0")

        for metric in METRIC_NAMES:
            if metric not in raw_metrics:
                raise ScoringError(f"missing metric: {metric}")
            raw = _to_decimal(raw_metrics[metric], metric)
            normalised = normalise_metric(raw, spec.normalisation[metric], spec.decimal_places)
            score += normalised * spec.weights[metric]
            metric_records[metric] = {
                "raw": _raw_metric_string(raw_metrics[metric]),
                "normalised": _decimal_string(normalised, spec.decimal_places),
            }

        return metric_records, score.quantize(quant)


def build_score_record(
    *,
    spec: ScoringSpec,
    raw_metrics: dict[str, str | int | Decimal],
    repo: str,
    mode: str,
    commit_sha: str,
    computed_at: str,
) -> dict[str, Any]:
    if mode not in {"repo", "commit"}:
        raise ScoringError("mode must be repo or commit")
    if not _COMMIT_RE.match(commit_sha):
        raise ScoringError("commit_sha must be a 40-character lowercase hex SHA")

    metrics, score = score_metrics(spec, raw_metrics)
    record: dict[str, Any] = {
        "poc": True,
        "spec_version": spec.spec_version,
        "spec_hash": spec.spec_hash,
        "mode": mode,
        "vcs": "git",
        "repo": repo,
        "commit_sha": commit_sha,
        "computed_at": computed_at,
        "tool_digests": dict(sorted(spec.tool_digests.items())),
        "metrics": metrics,
        "score": _decimal_string(score, spec.decimal_places),
        "score_decimal_places": spec.decimal_places,
    }
    record["record_hash"] = compute_record_hash(record)
    return record


def compute_record_hash(record: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(_require_string(record, "spec_hash").encode("utf-8"))
    digest.update(_require_string(record, "commit_sha").encode("utf-8"))
    digest.update(canonical_json_bytes(record["metrics"]))
    digest.update(canonical_json_bytes(record["tool_digests"]))
    return f"sha256:{digest.hexdigest()}"


def verify_record_hash(record: dict[str, Any]) -> bool:
    record_hash = record.get("record_hash")
    if not isinstance(record_hash, str):
        return False
    valid = compute_record_hash(record) == record_hash
    if not valid:
        # Verify path only — never invoked from the deterministic scoring pipeline,
        # so emitting this metric does not affect record_hash.
        from cce.otel import RECORD_HASH_MISMATCH_TOTAL

        spec_hash = record.get("spec_hash", "unknown")
        commit_sha = record.get("commit_sha", "unknown")
        RECORD_HASH_MISMATCH_TOTAL.labels(spec_hash=spec_hash, commit_sha=commit_sha).inc()
    return valid


@contextmanager
def _decimal_context() -> Iterator[None]:
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        yield


def _quantizer(decimal_places: int) -> Decimal:
    return Decimal("1").scaleb(-decimal_places)


def _to_decimal(value: str | int | Decimal, name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise ScoringError(f"{name} must be a string, int, or Decimal")


def _decimal_string(value: Decimal, decimal_places: int) -> str:
    quantized = value.quantize(_quantizer(decimal_places))
    return f"{quantized:.{decimal_places}f}"


def _raw_metric_string(value: str | int | Decimal) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _require_string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ScoringError(f"record.{key} must be a string")
    return value
