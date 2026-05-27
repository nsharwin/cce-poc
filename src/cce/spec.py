from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from cce.canonical import canonical_json_bytes

METRIC_NAMES = (
    "cyclomatic",
    "cognitive",
    "nesting_depth",
    "function_length",
    "file_length",
)

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SpecValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalisationRule:
    cuts: tuple[Decimal, ...]
    normalised: tuple[Decimal, ...]


@dataclass(frozen=True)
class ScoringSpec:
    spec_version: str
    spec_hash: str
    weights: dict[str, Decimal]
    normalisation: dict[str, NormalisationRule]
    decimal_places: int
    rounding_mode: str
    tool_digests: dict[str, str]
    raw: dict[str, Any]


def load_spec(path: Path) -> ScoringSpec:
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise SpecValidationError(f"invalid YAML in scoring spec: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SpecValidationError("scoring spec must be a YAML mapping")
    return spec_from_mapping(loaded)


def spec_from_mapping(mapping: dict[str, Any]) -> ScoringSpec:
    _reject_floats(mapping, path="scoring-spec.yaml")

    weights = _parse_weights(mapping.get("weights"))
    normalisation = _parse_normalisation(mapping.get("normalisation"))
    rounding = mapping.get("rounding")
    if not isinstance(rounding, dict):
        raise SpecValidationError("rounding must be a mapping")
    decimal_places = rounding.get("decimal_places")
    if not isinstance(decimal_places, int):
        raise SpecValidationError("rounding.decimal_places must be an integer")
    rounding_mode = rounding.get("mode")
    if rounding_mode != "ROUND_HALF_EVEN":
        raise SpecValidationError("rounding.mode must be ROUND_HALF_EVEN")

    spec_hash = _compute_spec_hash(mapping)
    tool_digests = _flatten_tool_digests(mapping.get("pinned_tools"))

    return ScoringSpec(
        spec_version=str(mapping.get("spec_version")),
        spec_hash=spec_hash,
        weights=weights,
        normalisation=normalisation,
        decimal_places=decimal_places,
        rounding_mode=rounding_mode,
        tool_digests=tool_digests,
        raw=dict(mapping),
    )


def validate_digest_shapes(tool_digests: dict[str, str]) -> None:
    for name, digest in sorted(tool_digests.items()):
        if not _SHA256_RE.match(digest):
            raise SpecValidationError(f"{name} must be a sha256:<64 lowercase hex> digest")


def _compute_spec_hash(mapping: dict[str, Any]) -> str:
    material = dict(mapping)
    material.pop("spec_hash", None)
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"sha256:{digest}"


def _parse_weights(value: Any) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        raise SpecValidationError("weights must be a mapping")

    weights: dict[str, Decimal] = {}
    for metric in METRIC_NAMES:
        raw = value.get(metric)
        if not isinstance(raw, str):
            raise SpecValidationError(f"weights.{metric} must be a quoted decimal string")
        weights[metric] = Decimal(raw)

    total = sum(weights.values(), Decimal("0"))
    if total != Decimal("1.00"):
        raise SpecValidationError("weights must sum to 1.00")
    return weights


def _parse_normalisation(value: Any) -> dict[str, NormalisationRule]:
    if not isinstance(value, dict):
        raise SpecValidationError("normalisation must be a mapping")
    if value.get("method") != "piecewise_linear_frozen_cuts":
        raise SpecValidationError("normalisation.method must be piecewise_linear_frozen_cuts")

    rules: dict[str, NormalisationRule] = {}
    for metric in METRIC_NAMES:
        raw_rule = value.get(metric)
        if not isinstance(raw_rule, dict):
            raise SpecValidationError(f"normalisation.{metric} must be a mapping")
        cuts = _parse_decimal_tuple(raw_rule.get("cuts"), f"normalisation.{metric}.cuts")
        normalised = _parse_decimal_tuple(
            raw_rule.get("normalised"),
            f"normalisation.{metric}.normalised",
        )
        if len(cuts) + 1 != len(normalised):
            raise SpecValidationError(f"normalisation.{metric} must have one more value than cut")
        if tuple(sorted(cuts)) != cuts:
            raise SpecValidationError(f"normalisation.{metric}.cuts must be sorted ascending")
        rules[metric] = NormalisationRule(cuts=cuts, normalised=normalised)
    return rules


def _parse_decimal_tuple(value: Any, path: str) -> tuple[Decimal, ...]:
    if not isinstance(value, list) or not value:
        raise SpecValidationError(f"{path} must be a non-empty list")
    decimals: list[Decimal] = []
    for item in value:
        if not isinstance(item, str):
            raise SpecValidationError(f"{path} values must be quoted decimal strings")
        decimals.append(Decimal(item))
    return tuple(decimals)


def _flatten_tool_digests(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SpecValidationError("pinned_tools must be a mapping")
    grammars = value.get("grammars")
    if not isinstance(grammars, dict):
        raise SpecValidationError("pinned_tools.grammars must be a mapping")

    tool_digests = {
        "tree_sitter_core": _require_digest(value, "tree_sitter_core"),
        "tree_sitter_python": _require_digest(grammars, "python"),
        "tree_sitter_typescript": _require_digest(grammars, "typescript"),
        "lizard": _require_digest(value, "lizard"),
        "scc": _require_digest(value, "scc"),
    }
    validate_digest_shapes(tool_digests)
    return tool_digests


def _require_digest(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise SpecValidationError(f"{key} must be a digest string")
    return value


def _reject_floats(value: Any, path: str) -> None:
    if isinstance(value, float):
        raise SpecValidationError(f"{path} must not contain floats; quote decimal values")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_floats(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_floats(child, f"{path}[{index}]")
