"""Tests for CLI error exit codes (10-14)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cce.cli import (
    EXIT_ANALYZER,
    EXIT_GIT,
    EXIT_SCORING,
    EXIT_SPEC,
    main,
)


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


def _valid_spec() -> str:
    return (
        'spec_version: "0.1.0"\n'
        "weights:\n"
        '  cyclomatic: "0.35"\n'
        '  cognitive: "0.35"\n'
        '  nesting_depth: "0.10"\n'
        '  function_length: "0.10"\n'
        '  file_length: "0.10"\n'
        "normalisation:\n"
        '  method: "piecewise_linear_frozen_cuts"\n'
        "  cyclomatic:\n"
        '    cuts: ["1", "10", "25"]\n'
        '    normalised: ["0.0", "0.5", "0.75", "1.0"]\n'
        "  cognitive:\n"
        '    cuts: ["0", "15", "30"]\n'
        '    normalised: ["0.0", "0.5", "0.75", "1.0"]\n'
        "  nesting_depth:\n"
        '    cuts: ["0", "3", "6"]\n'
        '    normalised: ["0.0", "0.5", "0.75", "1.0"]\n'
        "  function_length:\n"
        '    cuts: ["1", "50", "100"]\n'
        '    normalised: ["0.0", "0.5", "0.75", "1.0"]\n'
        "  file_length:\n"
        '    cuts: ["1", "300", "600"]\n'
        '    normalised: ["0.0", "0.5", "0.75", "1.0"]\n'
        "rounding:\n"
        "  decimal_places: 4\n"
        '  mode: "ROUND_HALF_EVEN"\n'
        "pinned_tools:\n"
        '  tree_sitter_core: "sha256:' + ("1" * 64) + '"\n'
        "  grammars:\n"
        '    python: "sha256:' + ("3" * 64) + '"\n'
        '    typescript: "sha256:' + ("4" * 64) + '"\n'
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True
    )
    (path / "main.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True,
        env={**subprocess.os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"}
    )


def test_exit_spec_bad_yaml(tmp_path: Path) -> None:
    spec = tmp_path / "bad.yaml"
    spec.write_text("{invalid yaml: [", encoding="utf-8")
    rc = main(["score", "--spec", str(spec), "--repo", ".", "--mode", "repo"])
    assert rc == EXIT_SPEC


def test_exit_spec_bad_digest_format(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        _valid_spec()
        + '  lizard: "not-a-valid-digest"\n'
        + '  scc: "sha256:' + ("6" * 64) + '"\n',
        encoding="utf-8",
    )
    rc = main([
        "score",
        "--spec", str(spec),
        "--repo", str(tmp_path),
        "--mode", "repo",
        "--verify-digests", "true",
    ])
    assert rc == EXIT_SPEC


def test_exit_git_bad_remote_repo(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        _valid_spec()
        + '  lizard: "sha256:' + ("5" * 64) + '"\n'
        + '  scc: "sha256:' + ("6" * 64) + '"\n',
        encoding="utf-8",
    )
    rc = main([
        "score",
        "--spec", str(spec),
        "--repo", "https://not.a.valid.git.repo.example",
        "--mode", "commit",
        "--commit", "0" * 40,
    ])
    assert rc == EXIT_GIT


def test_exit_analyzer_syntax_error(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        _valid_spec()
        + '  lizard: "sha256:' + ("5" * 64) + '"\n'
        + '  scc: "sha256:' + ("6" * 64) + '"\n',
        encoding="utf-8",
    )
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def foo(: pass\n", encoding="utf-8")
    rc = main([
        "score",
        "--spec", str(spec),
        "--repo", str(tmp_path),
        "--mode", "repo",
        "--verify-digests", "false",
    ])
    assert rc == EXIT_ANALYZER


def test_verify_rejects_mismatch(tmp_path: Path) -> None:
    record_path = tmp_path / "bad_record.json"
    record_path.write_text(json.dumps({
        "record_hash": "sha256:" + "0" * 64,
        "spec_hash": "sha256:" + "1" * 64,
        "commit_sha": "0" * 40,
        "metrics": {},
        "tool_digests": {},
        "score": "0.0",
        "computed_at": "2024-01-01T00:00:00Z",
    }), encoding="utf-8")
    rc = main(["verify", "--record", str(record_path)])
    assert rc == EXIT_SCORING
