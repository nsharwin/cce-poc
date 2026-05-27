# POC-M-4 Container + Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close `POC-M-4` from `docs/poc-prd.md` §8 — *"Dockerfile (pinned base + apt+pip with hashes). --network=none runtime. Hardened git clone. Submodule-trap fixture + test."* — by shipping the artifacts that satisfy `PREQ-A-2`, `PREQ-A-3`, `PREQ-X-1`, `PREQ-X-2`, `PREQ-X-3`, `POC-GATE-5`, and `POC-GATE-6`. Firecracker isolation (`PREQ-X-4`) stays explicitly deferred (Docker-only for POC, per `docs/poc-prd.md` §1 `out_of_scope_for_poc`).

**Architecture:**
1. **`PREQ-A-2`** — add a `Dockerfile` based on `python:3.12-slim-bookworm` pinned by **sha256 digest** (not tag). System deps installed with `apt-get install -y --no-install-recommends pkg=<exact-version>`; Python deps installed from a generated `requirements.lock.txt` (exported by `uv export --format=requirements-txt --no-emit-project --no-emit-workspace`) and verified with `pip install --require-hashes`. Add `.dockerignore` so build context is reproducible. The same digest is also written into `scoring-spec.yaml::worker_image` so the score record's `spec_hash` covers the image identity.
2. **`PREQ-A-3` (runtime) + `POC-GATE-5`** — `--network=none` is enforced at the Docker `docker run` boundary (not from inside Python). The CLI gains a small `cce.runtime.network` self-check (`assert_network_isolated()`) that opens a non-blocking TCP socket to `1.1.1.1:53` and fails fast if it *succeeds*. The check is opt-in via `CCE_REQUIRE_NETWORK_ISOLATED=1` (or `--assert-network-isolated`) so local dev is unaffected; CI flips the env var inside the container.
3. **`PREQ-X-1`** — add `_assert_git_min_version()` in `src/cce/git_ops.py` that reads `git_min_version` from `scoring-spec.yaml` and exits with the existing exit code `12` (clone/git safety failure, per `docs/poc-prd.md` §9.3) on mismatch. Called at the top of `prepared_repo`. The `Dockerfile` installs `git` from `bookworm-backports` (≥ 2.50.1) so the container always satisfies the gate.
4. **`PREQ-X-2`** — extend `prepared_repo`'s local-mode branch (the `repo_path.exists()` path in `src/cce/git_ops.py`, lines 17–20) with the same safety posture the remote path already has: refuse populated `.gitmodules`, refuse symlinks that resolve outside the repo root, and pass `-c protocol.file.allow=never -c core.symlinks=false -c submodule.recurse=false` to every git invocation. DEFERRED.md currently flags this gap.
5. **`POC-GATE-6`** — add a `tests/fixtures/submodule_trap/` mini-repo containing a crafted `.gitmodules` that points at a `file://` URL. `tests/test_submodule_trap.py` runs `cce score --repo <trap> --mode commit --commit <sha>` and accepts EITHER (a) success with submodules un-recursed and `.gitmodules` treated as inert text, OR (b) exit code `12` per the CLI contract — parameterised over both outcomes with a comment that explains the dual acceptance.
6. **`PREQ-X-3` / `POC-GATE-5` (CI)** — add a new `container-isolation` job to `.github/workflows/poc-determinism.yml` that builds the Dockerfile, runs `docker run --network=none …` against `tests/fixtures/simple_python`, asserts `curl -m2 https://example.com` exits non-zero inside the container, and feeds the resulting `record_hash` into the existing `compare-hashes` job. Scoped to `ubuntu-24.04` + `ubuntu-24.04-arm` only (macOS GitHub runners cannot run Linux containers natively).

**Tech Stack:** Python 3.12, uv 0.9.27, `python:3.12-slim-bookworm` (digest-pinned), Debian `bookworm-backports` for `git>=2.50.1`, pytest 9.0.3, `rfc8785==0.1.4`, Docker (BuildKit), GitHub Actions (`ubuntu-24.04`, `ubuntu-24.04-arm`).

---

## File Structure

**Creates:**
- `Dockerfile` — digest-pinned base, hash-pinned apt + pip, runs as non-root, default `ENTRYPOINT ["uv", "run", "cce"]`.
- `requirements.lock.txt` — `uv export` output with `--require-hashes`-compatible hashes for every transitive dep.
- `.dockerignore` — excludes `.git/`, `.venv/`, `cce-out/`, `tests/fixtures/grammar_spans/` (re-generatable), local `__pycache__/`, IDE folders.
- `src/cce/runtime.py` — exposes `assert_network_isolated()` and the `is_network_isolated()` probe.
- `tests/fixtures/submodule_trap/` — frozen mini git repo (a `.gitmodules` file plus one placeholder `.py` file) committed as plain files in the repo (the test will `git init` + `git commit` it deterministically, mirroring the env-var pattern in `.github/workflows/poc-determinism.yml`).
- `tests/test_submodule_trap.py` — `POC-GATE-6` test (parametrised over the two acceptable outcomes).
- `tests/test_git_ops.py` — unit tests for `_assert_git_min_version()` and the new local-mode hardening (only created if not already present at task time).
- `tests/test_runtime.py` — unit tests for `assert_network_isolated()` (monkeypatched socket).

**Modifies:**
- `src/cce/git_ops.py` — adds `_assert_git_min_version()`, hardens the local-mode branch, threads hardened `-c` flags through `_run_git`.
- `src/cce/cli.py` — wires `--assert-network-isolated` flag and the `CCE_REQUIRE_NETWORK_ISOLATED=1` env var; routes failures through the existing exit code map (no new codes needed — `12` covers git safety, a new code is NOT introduced; isolation failure uses `13` analyzer-adjacent path or simply raises before scoring with a clear message — final wire-up decided in Task 2).
- `scoring-spec.yaml` — fills in real `worker_image: "sha256:<digest>"` (currently a placeholder of `7777…`).
- `.github/workflows/poc-determinism.yml` — adds `container-isolation` job and extends `compare-hashes.needs`.
- `DEFERRED.md` — flips `PREQ-A-2`, `PREQ-A-3`, `PREQ-X-1`, `PREQ-X-2`, `PREQ-X-3`, `POC-GATE-6` to ✅ Closed with one-line citations.
- `README.md` — one-paragraph "Running in the pinned container" section pointing at `docker build` + `docker run --network=none …` commands.

**Does NOT touch:**
- `src/cce/scoring.py`, `src/cce/analyzer.py`, `src/cce/canonical.py` — POC-M-4 is purely about packaging and isolation; scoring math is frozen.

---

## Task 1: `PREQ-A-2` — Dockerfile + Lockfiles

**Why:** `PREQ-A-2` requires "Dockerfile with `FROM` pinned by digest, apt + pip pinned by version + hash". Currently no `Dockerfile` exists. The artifact must be byte-reproducible across builds so the image digest can be referenced from `scoring-spec.yaml::worker_image` and become part of `spec_hash`.

**Files:**
- Create: `Dockerfile`, `requirements.lock.txt`, `.dockerignore`.
- Modify: `scoring-spec.yaml` (fill in real `worker_image` digest at the end of this task).

- [ ] **Step 1: Look up the current `python:3.12-slim-bookworm` digest**

Run (from a host with Docker + buildx):

```bash
docker buildx imagetools inspect python:3.12-slim-bookworm | grep -E '^Name|^Digest'
```

Expected: prints `Name: docker.io/library/python:3.12-slim-bookworm` and a `Digest: sha256:<64hex>` line. Record the digest — this is the value to pin in `Dockerfile` and `scoring-spec.yaml`.

- [ ] **Step 2: Generate `requirements.lock.txt`**

Run:

```bash
uv export \
  --format=requirements-txt \
  --no-emit-project \
  --no-emit-workspace \
  --no-dev \
  --output-file=requirements.lock.txt
```

Verify: every line either begins with `#` (header) or is `pkg==version` followed by `--hash=sha256:<hex>` continuations. If any dependency is missing hashes, regenerate `uv.lock` first (`uv lock`).

- [ ] **Step 3: Write `.dockerignore`**

Create `.dockerignore` with exactly:

```
.git
.venv
__pycache__
*.pyc
cce-out
.pytest_cache
.ruff_cache
.idea
.vscode
node_modules
```

Rationale: `.git` must NOT be inside the image (the container scores **mounted** repos, never its own source). The `.dockerignore` also keeps the build context small enough that two `docker build` invocations are byte-deterministic.

- [ ] **Step 4: Write the `Dockerfile`**

Create `Dockerfile` (replace `<DIGEST>` with the value from Step 1; replace `<GIT_VERSION>` with the exact `bookworm-backports` git version at draft time):

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm@sha256:<DIGEST>

# Pinned apt: install git>=2.50.1 from bookworm-backports.
# PREQ-X-1 closure: container guarantees git client meets scoring-spec.yaml::git_min_version.
RUN set -eux; \
    echo "deb http://deb.debian.org/debian bookworm-backports main" \
      > /etc/apt/sources.list.d/backports.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends -t bookworm-backports \
      git=<GIT_VERSION> \
      ca-certificates=20230311+deb12u1; \
    apt-get install -y --no-install-recommends \
      curl=7.88.1-10+deb12u8; \
    rm -rf /var/lib/apt/lists/*; \
    git --version

# Pinned pip deps via hash-checked lock.
WORKDIR /opt/cce
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock.txt

# Project source.
COPY pyproject.toml README.md ./
COPY src ./src
COPY scoring-spec.yaml ./
RUN pip install --no-cache-dir --no-deps .

# Non-root for safety; scored repos are mounted read-only at /work.
RUN useradd --uid 1001 --create-home --shell /usr/sbin/nologin cce
USER cce
WORKDIR /work

ENTRYPOINT ["cce"]
CMD ["--help"]
```

- [ ] **Step 5: Reproducibility smoke**

Run:

```bash
docker build -t cce-poc:local-1 .
docker build -t cce-poc:local-2 .
docker image inspect cce-poc:local-1 --format '{{.Id}}'
docker image inspect cce-poc:local-2 --format '{{.Id}}'
```

Expected: the two `.Id` values are identical (BuildKit content-addressed layers + pinned inputs ⇒ same image id without `--no-cache`).

- [ ] **Step 6: Fill in `scoring-spec.yaml::worker_image`**

After Step 5 passes, push the built image to a content-addressable location (or use the local digest) and replace the placeholder line in `scoring-spec.yaml`:

```yaml
worker_image: "sha256:<DIGEST-from-Step-1>"
```

Note: `worker_image` is the **base image** digest (Step 1), not the final built-image id from Step 5. The base digest is the only value an external reviewer can independently verify with `docker buildx imagetools inspect`.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile requirements.lock.txt .dockerignore scoring-spec.yaml
git commit -m "feat: digest-pinned Dockerfile + hash-pinned deps (PREQ-A-2)"
```

---

## Task 2: `PREQ-X-1` + `PREQ-A-3` — Git Version Gate + Network-Isolation Self-Check

**Why:** `PREQ-X-1` requires `git >= 2.50.1` (per `scoring-spec.yaml::git_min_version`); the Dockerfile guarantees this inside the container but `cce` must also refuse to run on a host with stale git. `PREQ-A-3` requires runtime `--network=none` enforcement; the actual network namespace is owned by the Docker boundary, but `cce` should have a probe that fails fast if network is reachable when the operator asserts it should not be.

**Files:**
- Modify: `src/cce/git_ops.py` (add `_assert_git_min_version()` called from `prepared_repo`).
- Create: `src/cce/runtime.py` (network probe).
- Modify: `src/cce/cli.py` (wire `--assert-network-isolated` + env var).
- Create: `tests/test_git_ops.py` (if not present).
- Create: `tests/test_runtime.py`.

- [ ] **Step 1: Add `_assert_git_min_version()` to `src/cce/git_ops.py`**

Add a module-level helper that runs `git --version`, parses `git version X.Y.Z`, and compares as a tuple to the `git_min_version` string passed in by the caller. Raise `GitSafetyError` on mismatch. Call it at the top of `prepared_repo`. Sketch:

```python
def _assert_git_min_version(minimum: str) -> None:
    raw = _run_git(Path.cwd(), "--version")  # "git version 2.50.1"
    parsed = raw.removeprefix("git version ").split(".")
    actual = tuple(int(x) for x in parsed[:3])
    required = tuple(int(x) for x in minimum.split(".")[:3])
    if actual < required:
        raise GitSafetyError(
            f"git {minimum}+ required; found {raw}"
        )
```

`prepared_repo` accepts the minimum version as a new argument; the CLI threads `spec["git_min_version"]` into it.

- [ ] **Step 2: Add `src/cce/runtime.py`**

Create:

```python
"""PREQ-A-3 runtime network-isolation self-check.

We do NOT enforce network isolation from Python — that is the Docker
boundary's job (`docker run --network=none`). This module only *probes*
whether egress is reachable so CCE can fail fast when the operator
asserts (via `--assert-network-isolated` or `CCE_REQUIRE_NETWORK_ISOLATED=1`)
that the boundary should be in effect.
"""

from __future__ import annotations

import os
import socket


class NetworkIsolationError(RuntimeError):
    pass


def is_network_isolated(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.0) -> bool:
    """Return True iff a TCP connect to (host, port) fails within `timeout`."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except (TimeoutError, OSError):
        return True
    else:
        return False
    finally:
        sock.close()


def assert_network_isolated() -> None:
    """Raise NetworkIsolationError if network egress is reachable.

    Triggered by `--assert-network-isolated` CLI flag or
    `CCE_REQUIRE_NETWORK_ISOLATED=1` env var.
    """
    if not is_network_isolated():
        raise NetworkIsolationError(
            "network egress reachable; refusing to run under "
            "CCE_REQUIRE_NETWORK_ISOLATED=1 / --assert-network-isolated"
        )


def assert_network_isolated_if_required() -> None:
    if os.environ.get("CCE_REQUIRE_NETWORK_ISOLATED") == "1":
        assert_network_isolated()
```

- [ ] **Step 3: Wire the CLI flag in `src/cce/cli.py`**

Add `--assert-network-isolated` (bool, default False) to the `score` subparser. After arg parse and BEFORE `prepared_repo`:

```python
if args.assert_network_isolated or os.environ.get("CCE_REQUIRE_NETWORK_ISOLATED") == "1":
    from cce.runtime import assert_network_isolated
    assert_network_isolated()
```

Network-isolation failure must exit non-zero with a clear stderr message. Use exit code `12` (clone/git safety umbrella — the closest existing bucket per `docs/poc-prd.md` §9.3); document the choice with an inline comment.

- [ ] **Step 4: Unit-test the network probe**

Create `tests/test_runtime.py`:

```python
import socket
from unittest.mock import patch

import pytest

from cce.runtime import (
    NetworkIsolationError,
    assert_network_isolated,
    is_network_isolated,
)


def test_is_network_isolated_returns_true_when_connect_fails():
    with patch("socket.socket") as mk:
        inst = mk.return_value
        inst.connect.side_effect = OSError("Network is unreachable")
        assert is_network_isolated() is True


def test_is_network_isolated_returns_false_when_connect_succeeds():
    with patch("socket.socket") as mk:
        inst = mk.return_value
        inst.connect.return_value = None
        assert is_network_isolated() is False


def test_assert_raises_when_network_reachable():
    with patch("cce.runtime.is_network_isolated", return_value=False):
        with pytest.raises(NetworkIsolationError):
            assert_network_isolated()
```

- [ ] **Step 5: Unit-test the git version gate**

Create or append to `tests/test_git_ops.py`:

```python
import pytest

from cce.git_ops import GitSafetyError, _assert_git_min_version


def test_assert_git_min_version_passes_when_current_is_newer(monkeypatch):
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.50.1")
    _assert_git_min_version("2.50.1")  # no raise


def test_assert_git_min_version_fails_when_current_is_older(monkeypatch):
    monkeypatch.setattr("cce.git_ops._run_git", lambda *_a, **_k: "git version 2.43.0")
    with pytest.raises(GitSafetyError):
        _assert_git_min_version("2.50.1")
```

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`

Expected: all previously-green tests still pass + 5 new tests pass.

- [ ] **Step 7: Negative-control for the network probe (manual smoke)**

Run on a normal (networked) host:

```bash
CCE_REQUIRE_NETWORK_ISOLATED=1 uv run cce score \
  --spec ./scoring-spec.yaml \
  --repo ./tests/fixtures/simple_python \
  --mode repo \
  --verify-digests false
```

Expected: exits non-zero with the `network egress reachable` message. Then re-run **without** `CCE_REQUIRE_NETWORK_ISOLATED=1` and confirm it succeeds.

- [ ] **Step 8: Commit**

```bash
git add src/cce/git_ops.py src/cce/runtime.py src/cce/cli.py tests/test_git_ops.py tests/test_runtime.py
git commit -m "feat: git version gate + network-isolation self-check (PREQ-X-1, PREQ-A-3)"
```

---

## Task 3: `PREQ-X-2` — Harden Local-Mode Clone Path

**Why:** Today `src/cce/git_ops.py::prepared_repo` only hardens the **remote** clone path (lines 22–47). When `repo_path.exists()` is True (local mode, lines 17–20), it trusts the on-disk checkout entirely — DEFERRED.md `PREQ-X-2` calls this out. POC-M-4 requires the same safety posture in both modes: refuse populated `.gitmodules`, refuse symlinks escaping the repo root, and run every git invocation with hardened `-c` flags.

**Files:**
- Modify: `src/cce/git_ops.py` (extend the local-mode branch; thread hardened `-c` flags through `_run_git`).
- Modify: `tests/test_git_ops.py` (add three new cases).

- [ ] **Step 1: Add a `_assert_local_safety()` helper to `src/cce/git_ops.py`**

The helper accepts the repo root path and:
1. Refuses if `<root>/.gitmodules` exists with non-empty, non-comment content (matches the submodule-trap fixture pattern).
2. Walks the worktree with `os.walk(root, followlinks=False)`, calls `Path.resolve()` on every symlink, and raises `GitSafetyError` if the resolved target is not within `root.resolve()`.
3. Returns silently otherwise.

Sketch:

```python
def _assert_local_safety(root: Path) -> None:
    gm = root / ".gitmodules"
    if gm.is_file():
        content = gm.read_text(encoding="utf-8", errors="replace")
        non_empty = [
            line for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if non_empty:
            raise GitSafetyError(
                f"populated .gitmodules rejected in local mode: {gm}"
            )

    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                target = p.resolve()
                if root_resolved not in target.parents and target != root_resolved:
                    raise GitSafetyError(
                        f"symlink escapes repo root: {p} -> {target}"
                    )
```

Call `_assert_local_safety(repo_path)` at the very top of the `if repo_path.exists():` branch in `prepared_repo`, **before** `_resolve_local_commit`.

- [ ] **Step 2: Thread hardened `-c` flags through `_run_git` for local mode**

Refactor `_run_git` (or add a `_run_git_hardened` sibling) so that every local-mode invocation prepends `-c protocol.file.allow=never -c core.symlinks=false -c submodule.recurse=false`. The remote-clone block already passes these flags explicitly; the change is to also use them inside `_resolve_local_commit`.

- [ ] **Step 3: Add the three unit tests to `tests/test_git_ops.py`**

```python
import os
import subprocess
from pathlib import Path

import pytest

from cce.git_ops import GitSafetyError, prepared_repo


def _git_init(root: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, env=env)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return sha


def test_local_mode_rejects_populated_gitmodules(tmp_path):
    repo = tmp_path / "trap"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / ".gitmodules").write_text(
        '[submodule "evil"]\n\tpath = evil\n\turl = file:///etc\n'
    )
    sha = _git_init(repo)
    with pytest.raises(GitSafetyError, match=".gitmodules"):
        with prepared_repo(str(repo), "commit", sha) as _:
            pass


def test_local_mode_accepts_empty_or_commented_gitmodules(tmp_path):
    repo = tmp_path / "ok"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / ".gitmodules").write_text("# intentionally empty\n")
    sha = _git_init(repo)
    with prepared_repo(str(repo), "commit", sha) as (path, resolved):
        assert resolved == sha
        assert path == repo


def test_local_mode_rejects_symlink_escaping_root(tmp_path):
    repo = tmp_path / "esc"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (repo / "leak").symlink_to(outside)
    sha = _git_init(repo)
    with pytest.raises(GitSafetyError, match="symlink escapes"):
        with prepared_repo(str(repo), "commit", sha) as _:
            pass
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/test_git_ops.py -v`

Expected: all new tests pass, all pre-existing `test_git_ops.py` tests still pass.

- [ ] **Step 5: Negative-control — break the assertion, confirm the test catches it**

Temporarily comment out the `raise GitSafetyError(...)` inside `_assert_local_safety` for the `.gitmodules` branch and re-run `uv run pytest tests/test_git_ops.py::test_local_mode_rejects_populated_gitmodules -v`. Expected: **FAILS** (the test correctly catches the missing rejection). Then restore the raise and confirm green again.

- [ ] **Step 6: Commit**

```bash
git add src/cce/git_ops.py tests/test_git_ops.py
git commit -m "feat: harden local-mode clone path (PREQ-X-2)"
```

---

## Task 4: `POC-GATE-6` — Submodule-Trap Fixture + Test

**Why:** `POC-GATE-6` in `docs/poc-prd.md` §7 requires: *"Submodule-trap fixture (malicious .gitmodules) is rejected or safely no-ops; CCE-CVE-25 check green"*. The fixture must encode a real `.gitmodules` exploit attempt (a `file://` URL pointing at a host path) and the test must accept BOTH defensive outcomes — either CCE rejects with exit 12 (preferred, Task 3 closes this), or CCE succeeds while treating `.gitmodules` as inert text (the original POC-PRD acceptance per §7).

**Files:**
- Create: `tests/fixtures/submodule_trap/.gitmodules` (malicious content).
- Create: `tests/fixtures/submodule_trap/example.py` (placeholder so the repo isn't empty).
- Create: `tests/test_submodule_trap.py`.

- [ ] **Step 1: Create the fixture files**

```bash
mkdir -p tests/fixtures/submodule_trap
```

Create `tests/fixtures/submodule_trap/example.py`:

```python
def f(x: int) -> int:
    return x + 1
```

Create `tests/fixtures/submodule_trap/.gitmodules` with content that mimics a real CCE-CVE-25-style attack:

```
[submodule "evil"]
	path = evil
	url = file:///etc/passwd
	branch = main
[submodule "evil2"]
	path = evil2
	url = ../../../../etc/shadow
```

Tabs are intentional (matches the canonical `.gitmodules` format git emits).

- [ ] **Step 2: Write `tests/test_submodule_trap.py`**

```python
"""POC-GATE-6: malicious .gitmodules is rejected OR safely no-oped.

Per docs/poc-prd.md §7 POC-GATE-6 and §9.3 CLI exit codes, BOTH outcomes are acceptable:
  (a) `cce score` exits 12 (clone/git safety failure), OR
  (b) `cce score` exits 0 with .gitmodules treated as inert text (no submodule recursion).

After PREQ-X-2 (Task 3), CCE rejects in local mode (outcome a). If a future relaxation
re-enables outcome (b), this test still passes — that is the documented dual contract.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "submodule_trap"


def _git_init_fixture(work: Path) -> str:
    """Copy the fixture into a tmpdir and git-init it deterministically."""
    import shutil
    shutil.copytree(FIXTURE, work, dirs_exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CCE Test", "GIT_AUTHOR_EMAIL": "cce@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "CCE Test", "GIT_COMMITTER_EMAIL": "cce@example.test",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "trap"], cwd=work, check=True, env=env)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_submodule_trap_is_rejected_or_safely_noops(tmp_path: Path) -> None:
    work = tmp_path / "trap_repo"
    sha = _git_init_fixture(work)

    spec = Path(__file__).parent.parent / "scoring-spec.yaml"
    out = tmp_path / "cce-out"
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
        capture_output=True, text=True,
    )

    # POC-GATE-6: BOTH outcomes are acceptable.
    if proc.returncode == 0:
        # Safe no-op branch: .gitmodules treated as inert text.
        # Verify no `evil/` or `evil2/` submodule directories were created.
        assert not (work / "evil").exists(), "submodule was recursed; isolation broken"
        assert not (work / "evil2").exists(), "submodule was recursed; isolation broken"
    else:
        # Rejection branch: must be exit code 12 (clone/git safety), per §9.3.
        assert proc.returncode == 12, (
            f"unexpected exit {proc.returncode}; stderr={proc.stderr!r}"
        )
```

- [ ] **Step 3: Run the test**

Run: `uv run pytest tests/test_submodule_trap.py -v`

Expected after Task 3: PASS via the rejection branch (exit 12).

- [ ] **Step 4: Negative-control — neuter the fixture, confirm the test still passes via the no-op branch**

Temporarily blank the `.gitmodules` file in the fixture (`> tests/fixtures/submodule_trap/.gitmodules`) and re-run the test. Expected: PASS via the `proc.returncode == 0` branch (because PREQ-X-2 now lets an empty `.gitmodules` through). Then restore the fixture (`git checkout -- tests/fixtures/submodule_trap/.gitmodules`).

- [ ] **Step 5: Negative-control — break the safety, confirm the test FAILS**

Temporarily revert Task 3's `_assert_local_safety` (`git stash -- src/cce/git_ops.py`) AND simulate the unsafe path by manually creating an `evil/` directory inside the fixture before scoring. The test must then fail with `"submodule was recursed; isolation broken"`. Restore git_ops.py (`git stash pop`) and remove `evil/`. Confirm green.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`

Expected: previously-green count + new tests from Tasks 2, 3, 4 all green.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/submodule_trap/ tests/test_submodule_trap.py
git commit -m "test: submodule-trap fixture + dual-acceptance test (POC-GATE-6)"
```

---

## Task 5: `PREQ-X-3` + `POC-GATE-5` — Network-Isolation CI Job

**Why:** `POC-GATE-5` in `docs/poc-prd.md` §7 requires *"Network-isolation test passes (container has --network=none after clone; curl to internet fails)"*. The existing `.github/workflows/poc-determinism.yml` runs on **bare** GitHub runners — no container, no network isolation. This task adds a new `container-isolation` job that (a) builds the Dockerfile from Task 1, (b) runs the container with `--network=none`, (c) asserts `curl` egress fails, and (d) scores `tests/fixtures/simple_python` inside the container and feeds the hash into the existing `compare-hashes` job (closing PREQ-S-7 cross-environment determinism in the process).

**Files:**
- Modify: `.github/workflows/poc-determinism.yml` (add `container-isolation` job; extend `compare-hashes.needs`).

- [ ] **Step 1: Add the `container-isolation` job**

Append the following job to `.github/workflows/poc-determinism.yml` (after `deterministic-core`, before `compare-hashes`). Scope it to Linux runners only — `macos-15` cannot run Linux containers natively.

```yaml
  container-isolation:
    name: container-isolation-${{ matrix.name }}
    runs-on: ${{ matrix.runner }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: linux-x86_64
            runner: ubuntu-24.04
          - name: linux-arm64
            runner: ubuntu-24.04-arm
    steps:
      - name: Checkout
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd

      - name: Init fixture git repo (deterministic)
        env:
          GIT_AUTHOR_NAME: CCE Test
          GIT_AUTHOR_EMAIL: cce@example.test
          GIT_AUTHOR_DATE: "2026-01-01T00:00:00+0000"
          GIT_COMMITTER_NAME: CCE Test
          GIT_COMMITTER_EMAIL: cce@example.test
          GIT_COMMITTER_DATE: "2026-01-01T00:00:00+0000"
        run: |
          cd tests/fixtures/simple_python
          git init -q --initial-branch=main
          git config user.email "cce@example.test"
          git config user.name "CCE Test"
          git add .
          git commit -q -m "fixture"
          echo "Fixture HEAD: $(git rev-parse HEAD)"

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@988b5a0280414f521da01fcc63a27aeeb4b104db

      - name: Build CCE container image
        run: docker build -t cce-poc:ci .

      - name: PREQ-X-3 / POC-GATE-5 — assert curl egress FAILS under --network=none
        run: |
          set -eux
          # Run curl inside the container with --network=none. Must exit non-zero.
          if docker run --rm --network=none --entrypoint=curl cce-poc:ci -m2 https://example.com; then
            echo "FAIL: curl reached the internet under --network=none"
            exit 1
          fi
          echo "PASS: network egress correctly blocked"

      - name: Score fixture inside isolated container
        run: |
          mkdir -p cce-out
          HASH=$(docker run --rm \
            --network=none \
            -e CCE_REQUIRE_NETWORK_ISOLATED=1 \
            -v "$PWD:/work:ro" \
            -v "$PWD/cce-out:/work/cce-out" \
            cce-poc:ci \
            score \
              --spec /work/scoring-spec.yaml \
              --repo /work/tests/fixtures/simple_python \
              --mode repo \
              --out /work/cce-out \
              --verify-digests false)
          echo "$HASH" > cce-out/record_hash.txt
          echo "container HASH=$HASH"

      - name: Upload container record-hash artifact
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: record-hash-container-${{ matrix.name }}
          path: cce-out/record_hash.txt
```

- [ ] **Step 2: Extend `compare-hashes.needs`**

Update the existing `compare-hashes` job's `needs:` from `deterministic-core` to a list, so the `container-isolation` hashes are also gathered before comparison:

```yaml
  compare-hashes:
    name: Compare record hashes across runners
    runs-on: ubuntu-24.04
    needs:
      - deterministic-core
      - container-isolation
```

No change to the comparison logic is required — it already `find`s every `record_hash.txt` artifact and asserts a single unique value. The container hashes joining the matrix is exactly the cross-environment determinism `POC-GATE-5` calls for.

- [ ] **Step 3: Verify the workflow locally with `act` (optional but recommended)**

Run:

```bash
act -j container-isolation -W .github/workflows/poc-determinism.yml --container-architecture linux/amd64
```

Expected: the workflow step "PREQ-X-3 / POC-GATE-5 — assert curl egress FAILS" passes; the score step prints a `sha256:` line that matches the bare-runner hash.

- [ ] **Step 4: Negative-control — drop `--network=none`, confirm CI FAILS**

In a throwaway branch, edit Step "PREQ-X-3 / POC-GATE-5" to remove the `--network=none` flag from the `docker run` invocation. Push and verify the workflow run fails with `FAIL: curl reached the internet under --network=none`. Then revert.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/poc-determinism.yml
git commit -m "ci: container-isolation job + network-egress assertion (PREQ-X-3, POC-GATE-5)"
```

---

## Task 6: `DEFERRED.md` Closure + README Touch-Up

**Why:** Per `docs/poc-prd.md` §13 rule 7, every PRD requirement transition out of "Deferred" must be reflected in `DEFERRED.md` with a one-line citation of the file or test that closes it. README must also tell external reviewers how to reproduce the score inside the pinned container, per `docs/poc-prd.md` §11 deliverables.

**Files:**
- Modify: `DEFERRED.md` (flip six IDs to ✅ Closed with citations).
- Modify: `README.md` (one-paragraph "Running in the pinned container" section).

- [ ] **Step 1: Flip the six IDs in `DEFERRED.md`**

In `DEFERRED.md`, edit the following entries to ✅ Closed with the cited closing artifact:

- `PREQ-A-2`: ✅ Closed. Digest-pinned `Dockerfile` + hash-pinned `requirements.lock.txt` + `.dockerignore`. `worker_image` digest filled in `scoring-spec.yaml`.
- `PREQ-A-3`: ✅ Closed. Runtime `--network=none` enforced at the Docker boundary in `.github/workflows/poc-determinism.yml::container-isolation`; in-process probe at `src/cce/runtime.py::assert_network_isolated()` gated by `CCE_REQUIRE_NETWORK_ISOLATED=1` / `--assert-network-isolated`.
- `PREQ-X-1`: ✅ Closed. `src/cce/git_ops.py::_assert_git_min_version()` enforces `scoring-spec.yaml::git_min_version` at `prepared_repo` entry; container ships `git>=2.50.1` from `bookworm-backports`.
- `PREQ-X-2`: ✅ Closed. Local-mode branch of `src/cce/git_ops.py::prepared_repo` now calls `_assert_local_safety()` (rejects populated `.gitmodules` + symlinks escaping root); tests in `tests/test_git_ops.py`.
- `PREQ-X-3`: ✅ Closed. `.github/workflows/poc-determinism.yml::container-isolation` runs `curl -m2 https://example.com` under `--network=none` and asserts non-zero exit; job is in `compare-hashes.needs`.
- `POC-GATE-6`: ✅ Closed. `tests/fixtures/submodule_trap/.gitmodules` + `tests/test_submodule_trap.py` (dual-acceptance: exit 12 OR safe no-op per `docs/poc-prd.md` §7).

Leave `PREQ-X-4` (Firecracker) unchanged — still deferred per `docs/poc-prd.md` §1 `out_of_scope_for_poc`.

- [ ] **Step 2: Add the "Running in the pinned container" paragraph to `README.md`**

Append (or insert under the existing "Quick start" section). The block uses `~~~` fences so the inner ```bash``` snippets render cleanly:

~~~markdown
### Running in the pinned container (POC-M-4)

The repo ships a digest-pinned `Dockerfile` (`python:3.12-slim-bookworm@sha256:<digest>`)
that satisfies `PREQ-A-2`, `PREQ-A-3`, and `PREQ-X-1` (git >= 2.50.1 from
`bookworm-backports`). To reproduce a score under enforced network isolation:

```bash
docker build -t cce-poc:local .
docker run --rm \
  --network=none \
  -e CCE_REQUIRE_NETWORK_ISOLATED=1 \
  -v "$PWD:/work:ro" \
  -v "$PWD/cce-out:/work/cce-out" \
  cce-poc:local \
  score --spec /work/scoring-spec.yaml \
        --repo /work/tests/fixtures/simple_python \
        --mode repo \
        --out /work/cce-out \
        --verify-digests false
```

To regenerate the base image digest after a Debian point release:

```bash
docker buildx imagetools inspect python:3.12-slim-bookworm
```
~~~

- [ ] **Step 3: Commit**

```bash
git add DEFERRED.md README.md
git commit -m "docs: close PREQ-A-2/-A-3/-X-1/-X-2/-X-3 + POC-GATE-6; add container reproduction (POC-M-4)"
```

---

## Final Verification

- [ ] **Run the full unit suite**

Run: `uv run pytest -q`

Expected: all pre-existing tests still pass plus the new tests from Tasks 2, 3, 4 (`test_runtime.py` x3, `test_git_ops.py` x3 new local-mode + x2 version gate, `test_submodule_trap.py` x1). Approximate count: existing 16 + 9 new = **25 passed**.

- [ ] **Run the determinism gate**

Run: `uv run pytest tests/determinism_100x.py -q`

Expected: `1 passed` (unchanged — POC-M-4 must not regress PREQ-S-6).

- [ ] **Build the container locally**

Run: `docker build -t cce-poc:verify .`

Expected: succeeds; final image id matches a second `docker build` invocation (reproducibility).

- [ ] **Score under enforced network isolation**

Run:

```bash
mkdir -p /tmp/cce-verify
docker run --rm \
  --network=none \
  -e CCE_REQUIRE_NETWORK_ISOLATED=1 \
  -v "$PWD:/work:ro" \
  -v "/tmp/cce-verify:/work/cce-out" \
  cce-poc:verify \
  score --spec /work/scoring-spec.yaml \
        --repo /work/tests/fixtures/simple_python \
        --mode repo \
        --out /work/cce-out \
        --verify-digests false
ls /tmp/cce-verify/
```

Expected: prints `sha256:<hex>`; `/tmp/cce-verify/` contains `<hash>.json`, `<hash>.raw.json`, `<hash>.sha256`. The hash MUST match the bare-runner hash for the same fixture from the existing `deterministic-core` job.

- [ ] **Assert curl egress is blocked**

Run:

```bash
if docker run --rm --network=none --entrypoint=curl cce-poc:verify -m2 https://example.com; then
  echo "FAIL"; exit 1
else
  echo "PASS: --network=none blocks egress"
fi
```

Expected: `PASS: --network=none blocks egress`.

- [ ] **CI green**

Push the branch and confirm the new `container-isolation-linux-x86_64` and `container-isolation-linux-arm64` jobs pass, and the `compare-hashes` job still reports `Unique hashes: 1`.

---

## Self-Review Notes

- **Spec coverage:** Every PRD ID in scope is closed by a named artifact: `PREQ-A-2` → `Dockerfile`+`requirements.lock.txt`; `PREQ-A-3` → `--network=none` in CI + `src/cce/runtime.py`; `PREQ-X-1` → `_assert_git_min_version()`; `PREQ-X-2` → `_assert_local_safety()` + `tests/test_git_ops.py`; `PREQ-X-3` / `POC-GATE-5` → `container-isolation` CI job + curl-egress assertion; `POC-GATE-6` → `tests/test_submodule_trap.py` + fixture. `PREQ-X-4` (Firecracker) stays explicitly deferred — POC is Docker-only by design (`docs/poc-prd.md` §1).
- **Digest-regen workflow:** `python:3.12-slim-bookworm` rolls forward on Debian point releases. The README documents `docker buildx imagetools inspect python:3.12-slim-bookworm` as the single command to regenerate the digest; after editing the `Dockerfile` and `scoring-spec.yaml::worker_image`, re-run `docker build` twice to confirm reproducibility, then update both pins atomically in one commit.
- **arm64 / macOS scoping:** GitHub `macos-15` runners cannot run Linux containers natively, so the `container-isolation` matrix is deliberately limited to `ubuntu-24.04` + `ubuntu-24.04-arm`. Cross-architecture determinism for macOS is still covered by the existing `deterministic-core` matrix (which runs `uv run cce score` natively on `macos-15`); `compare-hashes` reconciles both into a single unique hash.
- **Submodule-trap dual acceptance:** Per `docs/poc-prd.md` §7 POC-GATE-6 wording, the test accepts either (a) exit 12 OR (b) safe no-op. After PREQ-X-2 lands, CCE rejects (a); the no-op branch (b) remains a valid contract for any future relaxation — both branches share the test, and the negative-control in Task 4 Step 5 exercises the no-op assertion path explicitly.
- **No new exit codes:** All new failure modes (git version too old, network egress reachable when asserted, populated `.gitmodules` in local mode, symlink escaping root) reuse exit code `12` ("clone or git safety failure") from `docs/poc-prd.md` §9.3. This avoids a CLI contract change while keeping failure semantics distinguishable via stderr messages.
- **No scoring-math changes:** Per `docs/poc-prd.md` §13 rule 6, POC-M-4 is purely about packaging and isolation. `src/cce/scoring.py`, `src/cce/analyzer.py`, and `src/cce/canonical.py` are untouched — the determinism contract is preserved by construction.
