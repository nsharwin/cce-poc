from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class GitSafetyError(RuntimeError):
    pass


@contextmanager
def prepared_repo(repo: str, mode: str, commit: str | None) -> Iterator[tuple[Path, str]]:
    repo_path = Path(repo)
    if repo_path.exists():
        commit_sha = _resolve_local_commit(repo_path, mode, commit)
        yield repo_path, commit_sha
        return

    if commit is None:
        raise GitSafetyError("--commit is required when --repo is a remote URL")

    with tempfile.TemporaryDirectory(prefix="cce-repo-") as tmpdir:
        clone_path = Path(tmpdir) / "repo"
        _run_git(
            Path(tmpdir),
            "clone",
            "--no-local",
            "--depth=1",
            "--filter=blob:none",
            "--no-checkout",
            repo,
            str(clone_path),
        )
        _run_git(
            clone_path,
            "-c",
            "protocol.file.allow=never",
            "-c",
            "core.symlinks=false",
            "-c",
            "submodule.recurse=false",
            "checkout",
            commit,
        )
        yield clone_path, commit


def _resolve_local_commit(repo_path: Path, mode: str, commit: str | None) -> str:
    if mode == "commit":
        if commit is None:
            raise GitSafetyError("--commit is required in commit mode")
        _run_git(repo_path, "cat-file", "-e", f"{commit}^{{commit}}")
        return commit
    return _run_git(repo_path, "rev-parse", "HEAD")


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitSafetyError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()
