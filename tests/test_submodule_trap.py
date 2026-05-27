"""POC-GATE-6: malicious .gitmodules is rejected OR safely no-oped.

Per ``docs/poc-prd.md`` §7 POC-GATE-6 and §9.3 CLI exit codes, BOTH outcomes
are acceptable:

  (a) ``cce score`` exits 12 (clone/git safety failure), OR
  (b) ``cce score`` exits 0 with ``.gitmodules`` treated as inert text
      (no submodule recursion).

After PREQ-X-2 (Task 3) landed, CCE rejects in local mode (outcome a). If a
future relaxation re-enables outcome (b), this test still passes — that is the
documented dual contract.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "submodule_trap"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_init_fixture(work: Path) -> str:
    """Copy the fixture into a tmpdir and git-init it deterministically."""
    shutil.copytree(FIXTURE, work, dirs_exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CCE Test",
        "GIT_AUTHOR_EMAIL": "cce@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "CCE Test",
        "GIT_COMMITTER_EMAIL": "cce@example.test",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=work, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=work, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "trap"], cwd=work, check=True, env=env)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_submodule_trap_is_rejected_or_safely_noops(tmp_path: Path) -> None:
    work = tmp_path / "trap_repo"
    sha = _git_init_fixture(work)

    spec = REPO_ROOT / "scoring-spec.yaml"
    out = tmp_path / "cce-out"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    proc = subprocess.run(
        [
            sys.executable, "-m", "cce", "score",
            "--spec", str(spec),
            "--repo", str(work),
            "--mode", "commit",
            "--commit", sha,
            "--out", str(out),
            "--verify-digests", "false",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    # POC-GATE-6: BOTH outcomes are acceptable.
    if proc.returncode == 0:
        # Safe no-op branch: .gitmodules treated as inert text.
        assert not (work / "evil").exists(), "submodule was recursed; isolation broken"
        assert not (work / "evil2").exists(), "submodule was recursed; isolation broken"
    else:
        # Rejection branch: must be exit code 12 (clone/git safety), per §9.3.
        assert proc.returncode == 12, (
            f"unexpected exit {proc.returncode}; stderr={proc.stderr!r}"
        )
        # And stderr must explain the rejection.
        assert ".gitmodules" in proc.stderr or "submodule" in proc.stderr.lower()
