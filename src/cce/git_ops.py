from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class GitSafetyError(RuntimeError):
    pass


class GitTimeoutError(RuntimeError):
    pass


# PREQ-X-2: hardened git config flags applied to every invocation. These were
# already present on the remote clone path; we now also use them when reading
# from an on-disk local checkout (commit mode).
_HARDENED_GIT_FLAGS: tuple[str, ...] = (
    "-c",
    "protocol.file.allow=never",
    "-c",
    "core.symlinks=false",
    "-c",
    "submodule.recurse=false",
)


@contextmanager
def prepared_repo(
    repo: str,
    mode: str,
    commit: str | None,
    git_min_version: str | None = None,
) -> Iterator[tuple[Path, str]]:
    if git_min_version is not None:
        _assert_git_min_version(git_min_version)

    repo_path = Path(repo)
    if repo_path.exists():
        # PREQ-X-2: local-mode hardening.
        _assert_local_safety(repo_path)
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
            timeout=300,
        )
        _run_git(
            clone_path,
            *_HARDENED_GIT_FLAGS,
            "checkout",
            commit,
            timeout=60,
        )
        yield clone_path, commit


def _resolve_local_commit(repo_path: Path, mode: str, commit: str | None) -> str:
    if mode == "commit":
        if commit is None:
            raise GitSafetyError("--commit is required in commit mode")
        _run_git(
            repo_path,
            *_HARDENED_GIT_FLAGS,
            "cat-file",
            "-e",
            f"{commit}^{{commit}}",
            timeout=30,
        )
        return commit
    return _run_git(repo_path, *_HARDENED_GIT_FLAGS, "rev-parse", "HEAD", timeout=30)


def _assert_git_min_version(minimum: str) -> None:
    """PREQ-X-1: refuse to run if the host's git client is older than ``minimum``.

    ``minimum`` is the dotted string from ``scoring-spec.yaml::git_min_version``
    (e.g. ``"2.50.1"``). Comparison is tuple-of-ints, so ``2.50.1`` > ``2.43.5``.
    """
    raw = _run_git(Path.cwd(), "--version", timeout=10)
    prefix = "git version "
    if not raw.startswith(prefix):
        raise GitSafetyError(f"unexpected git --version output: {raw!r}")
    try:
        actual = _parse_version(raw.removeprefix(prefix))
        required = _parse_version(minimum)
    except ValueError as exc:
        raise GitSafetyError(f"cannot parse git version: {exc}") from exc
    if actual < required:
        raise GitSafetyError(f"git {minimum}+ required; found {raw.removeprefix(prefix)}")


def _parse_version(text: str) -> tuple[int, int, int]:
    parts = text.strip().split(".")
    if len(parts) < 2:
        raise ValueError(f"unparsable version: {text!r}")
    # Take first three numeric components only; tolerate suffixes like "2.50.1.windows.1".
    nums: list[int] = []
    for component in parts[:3]:
        digits = ""
        for ch in component:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            raise ValueError(f"non-numeric version component in {text!r}")
        nums.append(int(digits))
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _assert_local_safety(root: Path) -> None:
    """PREQ-X-2: reject populated ``.gitmodules`` and symlinks escaping ``root``.

    Mirrors the safety posture the remote clone path already has (``--no-local``,
    ``protocol.file.allow=never``, ``core.symlinks=false``, ``submodule.recurse=false``)
    when the operator passes a path to an existing local checkout instead of a URL.
    """
    gm = root / ".gitmodules"
    if gm.is_file():
        try:
            content = gm.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise GitSafetyError(f"cannot read .gitmodules: {exc}") from exc
        non_empty = [
            line
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if non_empty:
            raise GitSafetyError(f"populated .gitmodules rejected in local mode: {gm}")

    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Skip walking into the .git directory.
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in list(dirnames) + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                try:
                    target = p.resolve()
                except OSError as exc:
                    raise GitSafetyError(f"cannot resolve symlink: {p} ({exc})") from exc
                if root_resolved != target and root_resolved not in target.parents:
                    raise GitSafetyError(f"symlink escapes repo root: {p} -> {target}")


def _run_git(cwd: Path, *args: str, timeout: int | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitTimeoutError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise GitSafetyError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()
