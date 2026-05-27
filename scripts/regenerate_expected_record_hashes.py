#!/usr/bin/env python3
"""Regenerate ``tests/fixtures/<name>/expected_record_hash.txt`` for each
Golden_Fixtures entry.

Spec: poc-readiness-hard-blockers, task 2.5/2.6.

Procedure (matches design.md §6 "Generation procedure"):

1. For each fixture in ``("simple_python", "simple_typescript", "perf_100k")``:
   a. (perf_100k only) regenerate the synthetic repo via
      ``python -m tests.fixtures.perf_100k.generate --out <fixture>/repo``.
   b. ``git init`` the fixture root with deterministic env vars
      (``GIT_AUTHOR_DATE``, ``GIT_COMMITTER_DATE``, name, email) so that
      the same source tree always produces the same git OID.
   c. Run ``cce score --spec ./scoring-spec.yaml --repo <fixture_root> \
      --mode repo --out <tmp>/cce-out`` (no ``--verify-digests false``).
   d. Capture the printed ``record_hash`` and write it to
      ``tests/fixtures/<name>/expected_record_hash.txt`` (trailing ``\n``).

The script is safe to re-run: each fixture is git-init'd into a fresh
copy under a temp directory so the live ``tests/fixtures/`` tree is left
untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "scoring-spec.yaml"
FIXTURES = ("simple_python", "simple_typescript", "perf_100k")

DETERMINISTIC_GIT_ENV = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_AUTHOR_NAME": "CCE Test",
    "GIT_AUTHOR_EMAIL": "cce@example.test",
    "GIT_COMMITTER_NAME": "CCE Test",
    "GIT_COMMITTER_EMAIL": "cce@example.test",
}


def _git_init_fixture(fixture_root: Path) -> None:
    env = {**os.environ, **DETERMINISTIC_GIT_ENV}
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main"],
        cwd=fixture_root,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", DETERMINISTIC_GIT_ENV["GIT_AUTHOR_EMAIL"]],
        cwd=fixture_root,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", DETERMINISTIC_GIT_ENV["GIT_AUTHOR_NAME"]],
        cwd=fixture_root,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=fixture_root,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"],
        cwd=fixture_root,
        env=env,
        check=True,
    )


def _materialise_fixture(name: str, dest_root: Path) -> Path:
    """Copy fixture sources into ``dest_root/<name>`` and return the path
    that ``cce score --repo`` should be pointed at."""
    src_root = REPO_ROOT / "tests" / "fixtures" / name
    dest = dest_root / name
    dest.mkdir(parents=True, exist_ok=True)

    if name == "perf_100k":
        # Generate the synthetic 100k LoC repo into dest/repo, mirroring the
        # CI workflow that will use `--out tests/fixtures/perf_100k/repo`.
        repo_dir = dest / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.fixtures.perf_100k.generate",
                "--out",
                str(repo_dir),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        return repo_dir

    # simple_python / simple_typescript: copy committed source files.
    for entry in src_root.iterdir():
        if entry.name in {"expected_record_hash.txt", ".git"}:
            continue
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
    return dest


def _run_cce_score(fixture_dir: Path, out_dir: Path) -> str:
    cmd = [
        str(REPO_ROOT / ".venv" / "bin" / "cce"),
        "score",
        "--spec",
        str(SPEC_PATH),
        "--repo",
        str(fixture_dir),
        "--mode",
        "repo",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise SystemExit(
            f"empty cce score output for {fixture_dir}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    record_hash = lines[-1].strip()
    if not record_hash.startswith("sha256:"):
        raise SystemExit(
            f"unexpected cce score output for {fixture_dir}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    return record_hash


def main() -> int:
    for name in FIXTURES:
        with tempfile.TemporaryDirectory(prefix=f"cce-{name}-") as tmpdir:
            tmp_path = Path(tmpdir)
            fixture_dir = _materialise_fixture(name, tmp_path / "src")
            _git_init_fixture(fixture_dir)
            out_dir = tmp_path / "cce-out"
            out_dir.mkdir()
            record_hash = _run_cce_score(fixture_dir, out_dir)
        target = REPO_ROOT / "tests" / "fixtures" / name / "expected_record_hash.txt"
        target.write_text(record_hash + "\n", encoding="utf-8")
        print(f"  {name:20s}  {record_hash}")
        print(f"    written to {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
