"""Reviewer receipt invariants for POC-GATE-4.

Spec: poc-readiness-hard-blockers, task 3.5.
Validates Requirements 5.1, 5.2, 5.3, 5.5.

The first three tests are skipped when no receipts have landed yet (the legal
pre-launch state per `DEFERRED.md`). Once at least one receipt is committed,
they enforce format and record_hash-equality invariants. The DEFERRED.md test
asserts the gate flips closed iff receipts exist.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPTS_DIR = REPO_ROOT / "docs" / "reproductions"
DEFERRED = REPO_ROOT / "DEFERRED.md"

RECEIPT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9_-]+\.txt$")
RECORD_HASH_RE = re.compile(r"^record_hash\s*=\s*(sha256:[0-9a-f]{64})\s*$", re.MULTILINE)
HEADER_KEYS = ("Reviewer", "Date", "Repo", "Commit", "Image", "Host OS", "Fixture")
HEADER_RE = {key: re.compile(rf"^#\s*{re.escape(key)}:\s*(.+)$", re.MULTILINE) for key in HEADER_KEYS}


def _receipts() -> list[Path]:
    if not RECEIPTS_DIR.is_dir():
        return []
    return sorted(p for p in RECEIPTS_DIR.iterdir() if RECEIPT_NAME_RE.match(p.name))


def test_at_least_one_receipt_exists_or_gate_open() -> None:
    """If at least one receipt exists, POC-GATE-4 should be closed in DEFERRED.md.
    If none exist, the gate stays explicitly open. Either state is legal."""
    receipts = _receipts()
    text = DEFERRED.read_text(encoding="utf-8")
    if receipts:
        assert "POC-GATE-4: ✅ Closed" in text or "POC-GATE-4: closed" in text.lower(), (
            "Receipts exist but DEFERRED.md does not mark POC-GATE-4 closed"
        )
    else:
        # Pre-launch: gate must still mention pending state.
        assert "POC-GATE-4" in text, "DEFERRED.md missing POC-GATE-4 reference"


@pytest.mark.parametrize("receipt", _receipts(), ids=lambda p: p.name)
def test_receipt_format_conforms(receipt: Path) -> None:
    """Receipt has all required header keys and exactly one record_hash line."""
    text = receipt.read_text(encoding="utf-8")
    for key, regex in HEADER_RE.items():
        match = regex.search(text)
        assert match, f"{receipt.name}: missing header `# {key}:`"
        assert match.group(1).strip(), f"{receipt.name}: empty `# {key}:` value"
    hash_matches = RECORD_HASH_RE.findall(text)
    assert len(hash_matches) == 1, (
        f"{receipt.name}: expected exactly one `record_hash = sha256:<hex>` "
        f"line, got {len(hash_matches)}"
    )


@pytest.mark.parametrize("receipt", _receipts(), ids=lambda p: p.name)
def test_receipt_record_hash_matches_frozen(receipt: Path) -> None:
    """Receipt record_hash equals expected_record_hash.txt for the named
    Fixture at the named Commit. If Commit == HEAD, read the file directly;
    otherwise use ``git show <commit>:<path>``."""
    text = receipt.read_text(encoding="utf-8")
    fixture_match = HEADER_RE["Fixture"].search(text)
    commit_match = HEADER_RE["Commit"].search(text)
    record_hash_match = RECORD_HASH_RE.search(text)
    assert fixture_match and commit_match and record_hash_match
    fixture_path = fixture_match.group(1).strip()
    # Accept either "tests/fixtures/<name>" or just "<name>".
    fixture_name = fixture_path.removeprefix("tests/fixtures/").strip("/")
    commit = commit_match.group(1).strip()
    receipt_hash = record_hash_match.group(1).strip()

    expected_path = REPO_ROOT / "tests" / "fixtures" / fixture_name / "expected_record_hash.txt"
    if not expected_path.is_file():
        pytest.fail(f"{receipt.name}: Fixture `{fixture_path}` has no Expected_Hash_File")

    # Try git show at the named commit; fall back to working-tree contents.
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:tests/fixtures/{fixture_name}/expected_record_hash.txt"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        expected_text = result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Commit not in local clone (e.g. shallow clone in CI); fall back.
        expected_text = expected_path.read_text(encoding="utf-8")

    expected_hash = expected_text.strip()
    assert receipt_hash == expected_hash, (
        f"{receipt.name}: record_hash {receipt_hash!r} != "
        f"Expected_Hash_File for fixture={fixture_name} at commit={commit}: "
        f"{expected_hash!r}"
    )


def test_deferred_md_marks_gate4_closed_iff_receipt_present() -> None:
    """DEFERRED.md flips POC-GATE-4 to ✅ Closed exactly when ≥ 1 receipt exists."""
    receipts = _receipts()
    text = DEFERRED.read_text(encoding="utf-8")
    closed_marker_present = "POC-GATE-4: ✅ Closed" in text
    if receipts:
        assert closed_marker_present, (
            "Receipts present but DEFERRED.md does not mark POC-GATE-4 closed"
        )
    else:
        assert not closed_marker_present, (
            "DEFERRED.md marks POC-GATE-4 closed but no receipt has landed"
        )
