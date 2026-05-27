"""Expected_Hash_File presence + shape invariants.

Spec: poc-readiness-hard-blockers, task 2.8.
Validates Requirements 3.1, 3.2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FIXTURES = ("simple_python", "simple_typescript", "perf_100k")

SHAPE = re.compile(rb"^sha256:[0-9a-f]{64}\n$")
PLACEHOLDER = re.compile(rb"^sha256:([0-9a-f])\1{63}\n$")


def _fixture_path(name: str) -> Path:
    return REPO_ROOT / "tests" / "fixtures" / name / "expected_record_hash.txt"


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_each_fixture_has_expected_hash_file(name: str) -> None:
    """For each entry in Golden_Fixtures, an Expected_Hash_File exists."""
    target = _fixture_path(name)
    assert target.is_file(), f"missing Expected_Hash_File: {target}"


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_each_expected_hash_file_shape(name: str) -> None:
    """Each Expected_Hash_File matches ^sha256:[0-9a-f]{64}\\n$ exactly."""
    contents = _fixture_path(name).read_bytes()
    assert SHAPE.fullmatch(contents), (
        f"{name}/expected_record_hash.txt has bad shape: {contents!r}"
    )


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_no_expected_hash_is_placeholder(name: str) -> None:
    """No Expected_Hash_File is `sha256:` followed by a single repeating
    hex digit (the placeholder pattern)."""
    contents = _fixture_path(name).read_bytes()
    assert not PLACEHOLDER.fullmatch(contents), (
        f"{name}/expected_record_hash.txt is a placeholder: {contents!r}"
    )
