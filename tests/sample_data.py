from __future__ import annotations

from pathlib import Path

COMMIT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def sample_spec_mapping() -> dict[str, object]:
    return {
        "spec_version": "0.1.0",
        "spec_hash": "sha256:" + ("1" * 64),
        "languages": ["python", "typescript"],
        "weights": {
            "cyclomatic": "0.30",
            "cognitive": "0.30",
            "nesting_depth": "0.15",
            "file_length": "0.10",
            "function_length": "0.15",
        },
        "normalisation": {
            "method": "piecewise_linear_frozen_cuts",
            "cyclomatic": {
                "cuts": ["5", "10", "20", "50"],
                "normalised": ["0.00", "0.25", "0.50", "0.75", "1.00"],
            },
            "cognitive": {
                "cuts": ["5", "15", "30", "60"],
                "normalised": ["0.00", "0.25", "0.50", "0.75", "1.00"],
            },
            "nesting_depth": {
                "cuts": ["2", "4", "6", "8"],
                "normalised": ["0.00", "0.25", "0.50", "0.75", "1.00"],
            },
            "function_length": {
                "cuts": ["20", "50", "100", "200"],
                "normalised": ["0.00", "0.25", "0.50", "0.75", "1.00"],
            },
            "file_length": {
                "cuts": ["100", "300", "600", "1000"],
                "normalised": ["0.00", "0.25", "0.50", "0.75", "1.00"],
            },
        },
        "rounding": {
            "decimal_places": 4,
            "mode": "ROUND_HALF_EVEN",
        },
        "pinned_tools": {
            "tree_sitter_core": "sha256:" + ("2" * 64),
            "grammars": {
                "python": "sha256:" + ("3" * 64),
                "typescript": "sha256:" + ("4" * 64),
            },
            "lizard": "sha256:" + ("5" * 64),
            "scc": "sha256:" + ("6" * 64),
        },
        "worker_image": "sha256:" + ("7" * 64),
        "git_min_version": "2.50.1",
        "canonicalisation": "RFC8785",
        "hash_algorithm": "sha256",
    }


def sample_raw_metrics() -> dict[str, str]:
    return {
        "cyclomatic": "35",
        "cognitive": "15",
        "nesting_depth": "5",
        "function_length": "100",
        "file_length": "450",
    }


def write_sample_spec(path: Path) -> None:
    path.write_text(
        """\
spec_version: 0.1.0
spec_hash: "sha256:1111111111111111111111111111111111111111111111111111111111111111"
languages:
  - python
  - typescript
weights:
  cyclomatic: "0.30"
  cognitive: "0.30"
  nesting_depth: "0.15"
  file_length: "0.10"
  function_length: "0.15"
normalisation:
  method: "piecewise_linear_frozen_cuts"
  cyclomatic:
    cuts: ["5", "10", "20", "50"]
    normalised: ["0.00", "0.25", "0.50", "0.75", "1.00"]
  cognitive:
    cuts: ["5", "15", "30", "60"]
    normalised: ["0.00", "0.25", "0.50", "0.75", "1.00"]
  nesting_depth:
    cuts: ["2", "4", "6", "8"]
    normalised: ["0.00", "0.25", "0.50", "0.75", "1.00"]
  function_length:
    cuts: ["20", "50", "100", "200"]
    normalised: ["0.00", "0.25", "0.50", "0.75", "1.00"]
  file_length:
    cuts: ["100", "300", "600", "1000"]
    normalised: ["0.00", "0.25", "0.50", "0.75", "1.00"]
rounding:
  decimal_places: 4
  mode: ROUND_HALF_EVEN
pinned_tools:
  tree_sitter_core: "sha256:2222222222222222222222222222222222222222222222222222222222222222"
  grammars:
    python: "sha256:3333333333333333333333333333333333333333333333333333333333333333"
    typescript: "sha256:4444444444444444444444444444444444444444444444444444444444444444"
  lizard: "sha256:5555555555555555555555555555555555555555555555555555555555555555"
  scc: "sha256:6666666666666666666666666666666666666666666666666666666666666666"
worker_image: "sha256:7777777777777777777777777777777777777777777777777777777777777777"
git_min_version: "2.50.1"
canonicalisation: "RFC8785"
hash_algorithm: "sha256"
""",
        encoding="utf-8",
    )
