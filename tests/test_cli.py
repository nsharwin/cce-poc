from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from cce.canonical import canonical_json_bytes
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


def test_sidecar_files_have_canonical_contents(tmp_path: Path, capsys) -> None:
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
    assert exit_code == 0
    record_hash = capsys.readouterr().out.strip()

    record_file = out_dir / f"{record_hash}.json"
    raw_file = out_dir / f"{record_hash}.raw.json"
    sha_file = out_dir / f"{record_hash}.sha256"

    record_bytes = record_file.read_bytes()
    raw_bytes = raw_file.read_bytes()

    record = json.loads(record_bytes)
    raw = json.loads(raw_bytes)

    # (a) record JSON is RFC 8785 canonical bytes
    assert record_bytes == canonical_json_bytes(record)

    # (b) raw JSON is RFC 8785 canonical bytes, with files[] sorted by path ascending
    assert raw_bytes == canonical_json_bytes(raw)
    paths = [entry["path"] for entry in raw["files"]]
    assert paths == sorted(paths)

    # (c) .sha256 sidecar is GNU-coreutils format: "<hex>  <record_hash>.json\n"
    #     so external users can run `cd <out_dir> && sha256sum -c <file>` directly.
    expected_digest = hashlib.sha256(record_bytes).hexdigest()
    assert sha_file.read_text(encoding="utf-8") == (
        f"{expected_digest}  {record_hash}.json\n"
    )


def test_verify_accepts_legacy_and_new_sidecar(tmp_path: Path, capsys) -> None:
    """`cce verify --sidecar` must accept both legacy and new sidecar formats."""
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
    sidecar = out_dir / f"{record_hash}.sha256"

    # New format (default): verify succeeds.
    assert main(["verify", "--sidecar", str(sidecar)]) == 0

    # Legacy format: rewrite as "sha256:<hex>\n" and verify still succeeds.
    record_bytes = (out_dir / f"{record_hash}.json").read_bytes()
    legacy_hex = hashlib.sha256(record_bytes).hexdigest()
    sidecar.write_text(f"sha256:{legacy_hex}\n", encoding="utf-8")
    assert main(["verify", "--sidecar", str(sidecar)]) == 0

    # Tamper case: a malformed digest must fail non-zero.
    sidecar.write_text(
        f"0000000000000000000000000000000000000000000000000000000000000000  {record_hash}.json\n",
        encoding="utf-8",
    )
    assert main(["verify", "--sidecar", str(sidecar)]) != 0


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
