from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cce.cli import main
from tests.sample_data import write_sample_spec


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "cce@example.test")
    run_git(repo, "config", "user.name", "CCE Test")
    package = repo / "pkg"
    package.mkdir()
    (package / "example.py").write_text(
        """\
def score(value):
    if value > 10:
        for item in range(value):
            if item % 2 == 0:
                return item
    return 0
""",
        encoding="utf-8",
    )
    run_git(repo, "add", "pkg/example.py")
    run_git(repo, "commit", "-m", "add fixture")
    return repo, run_git(repo, "rev-parse", "HEAD")


def test_score_cli_writes_record_raw_and_sha256_files(tmp_path: Path, capsys) -> None:
    repo, commit_sha = make_fixture_repo(tmp_path)
    spec_path = tmp_path / "scoring-spec.yaml"
    out_dir = tmp_path / "cce-out"
    write_sample_spec(spec_path)

    exit_code = main(
        [
            "score",
            "--spec",
            str(spec_path),
            "--repo",
            str(repo),
            "--mode",
            "commit",
            "--commit",
            commit_sha,
            "--out",
            str(out_dir),
            "--verify-digests",
            "false",
        ]
    )

    stdout = capsys.readouterr().out.strip()
    record_file = out_dir / f"{stdout}.json"
    raw_file = out_dir / f"{stdout}.raw.json"
    sha_file = out_dir / f"{stdout}.sha256"

    assert exit_code == 0
    assert stdout.startswith("sha256:")
    assert record_file.is_file()
    assert raw_file.is_file()
    assert sha_file.is_file()

    record = json.loads(record_file.read_text(encoding="utf-8"))
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    assert record["commit_sha"] == commit_sha
    assert record["record_hash"] == stdout
    assert set(raw) == {"files", "summary"}


def test_verify_cli_accepts_untampered_record(tmp_path: Path, capsys) -> None:
    repo, commit_sha = make_fixture_repo(tmp_path)
    spec_path = tmp_path / "scoring-spec.yaml"
    out_dir = tmp_path / "cce-out"
    write_sample_spec(spec_path)

    assert (
        main(
            [
                "score",
                "--spec",
                str(spec_path),
                "--repo",
                str(repo),
                "--mode",
                "commit",
                "--commit",
                commit_sha,
                "--out",
                str(out_dir),
                "--verify-digests",
                "false",
            ]
        )
        == 0
    )
    record_hash = capsys.readouterr().out.strip()

    assert main(["verify", "--record", str(out_dir / f"{record_hash}.json")]) == 0
