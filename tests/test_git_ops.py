"""Unit tests for src/cce/git_ops.py (PREQ-X-1, PREQ-X-2)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cce.git_ops import (
    GitSafetyError,
    _assert_git_min_version,
    prepared_repo,
)

# -- PREQ-X-1: git version gate -------------------------------------------------


def test_assert_git_min_version_passes_when_current_is_newer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.50.1")
    _assert_git_min_version("2.50.1")  # no raise


def test_assert_git_min_version_passes_when_current_is_much_newer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.51.0")
    _assert_git_min_version("2.50.1")  # no raise


def test_assert_git_min_version_fails_when_current_is_older(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.43.0")
    with pytest.raises(GitSafetyError, match=r"2\.50\.1\+"):
        _assert_git_min_version("2.50.1")


def test_assert_git_min_version_tolerates_trailing_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.50.1.windows.1")
    _assert_git_min_version("2.50.1")


# -- PREQ-X-2: local-mode hardening --------------------------------------------


def _git_init(root: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@e",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, env=env)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_local_mode_rejects_populated_gitmodules(tmp_path: Path) -> None:
    repo = tmp_path / "trap"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / ".gitmodules").write_text(
        '[submodule "evil"]\n\tpath = evil\n\turl = file:///etc/passwd\n'
    )
    sha = _git_init(repo)
    with (
        pytest.raises(GitSafetyError, match=".gitmodules"),
        prepared_repo(str(repo), "commit", sha),
    ):
        pass


def test_local_mode_accepts_empty_or_commented_gitmodules(tmp_path: Path) -> None:
    repo = tmp_path / "ok"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / ".gitmodules").write_text("# intentionally empty\n")
    sha = _git_init(repo)
    with prepared_repo(str(repo), "commit", sha) as (path, resolved):
        assert resolved == sha
        assert path == repo


def test_local_mode_rejects_symlink_escaping_root(tmp_path: Path) -> None:
    repo = tmp_path / "esc"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (repo / "leak").symlink_to(outside)
    sha = _git_init(repo)
    with (
        pytest.raises(GitSafetyError, match="symlink escapes"),
        prepared_repo(str(repo), "commit", sha),
    ):
        pass


def test_local_mode_accepts_internal_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "ok2"
    repo.mkdir()
    (repo / "real.py").write_text("y = 2\n")
    (repo / "link.py").symlink_to(repo / "real.py")
    sha = _git_init(repo)
    with prepared_repo(str(repo), "commit", sha) as (path, resolved):
        assert resolved == sha
        assert path == repo


# -- Input validation: commit ref and repo scheme ------------------------------


def test_prepared_repo_rejects_option_like_commit_ref():
    """A commit ref that looks like a git option must be rejected before any
    subprocess call. Defense-in-depth against CLI callers that bypass the API
    validator."""
    with (
        pytest.raises(GitSafetyError, match="invalid commit"),
        prepared_repo(
            repo="https://example.invalid/repo.git",
            mode="commit",
            commit="--upload-pack=touch /tmp/pwned",
        ),
    ):
        pass


def test_prepared_repo_rejects_non_hex_commit():
    with (
        pytest.raises(GitSafetyError, match="invalid commit"),
        prepared_repo(
            repo="https://example.invalid/repo.git",
            mode="commit",
            commit="HEAD~1",
        ),
    ):
        pass


def test_prepared_repo_rejects_unsupported_repo_scheme():
    """Repo strings that are neither a supported scheme nor an existing local
    path must be rejected."""
    with (
        pytest.raises(GitSafetyError, match="unsupported repo"),
        prepared_repo(
            repo="ext::sh -c whoami",
            mode="commit",
            commit="a" * 40,
        ),
    ):
        pass
