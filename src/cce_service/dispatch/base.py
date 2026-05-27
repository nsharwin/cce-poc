"""Dispatcher Protocol + in-process fake for tests.

A ``Dispatcher`` is the boundary between the API layer and the worker
runtime. The production implementation
(:mod:`cce_service.dispatch.firecracker`) launches a per-job microVM;
the in-process implementation runs scoring synchronously in the same
process and is used in unit tests.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any, Protocol

from cce_service.storage import JobRecord


class DispatchError(RuntimeError):
    """Any failure during dispatch (boot, exec, exit, persistence)."""


@dataclass(frozen=True)
class DispatchResult:
    record_hash: str
    score: str
    metrics: dict[str, Any]
    spec_hash: str
    tool_digests: dict[str, str]
    sidecars: dict[str, str]


class Dispatcher(Protocol):
    def dispatch(self, job: JobRecord) -> DispatchResult: ...


class InProcessDispatcher:
    """Runs ``cce score`` in the current process. Test-only.

    Uses the deterministic core directly (``analyse_repo`` +
    ``build_score_record``) to avoid forking ``cce`` CLI in tests. Repos
    are cloned shallowly to a tmp dir; the caller is responsible for
    keeping the dispatcher alive until the result is consumed.
    """

    def __init__(
        self,
        *,
        spec_path: Path,
        repo_clone: Any | None = None,
    ) -> None:
        self.spec_path = spec_path
        # ``repo_clone`` is a callable so tests can inject a local fixture
        # path instead of cloning from a URL.
        self.repo_clone = repo_clone or _default_clone

    def dispatch(self, job: JobRecord) -> DispatchResult:
        import hashlib
        from datetime import datetime

        from cce.analyzer import analyse_repo
        from cce.canonical import canonical_json_bytes
        from cce.scoring import build_score_record
        from cce.spec import load_spec

        spec = load_spec(self.spec_path)
        with tempfile.TemporaryDirectory(prefix="cce-dispatch-") as tmp:
            repo_path = self.repo_clone(job.repo_url, job.commit_sha, Path(tmp))
            raw_metrics, raw_payload = analyse_repo(repo_path)
            record = build_score_record(
                spec=spec,
                raw_metrics=raw_metrics,
                repo=job.repo_url,
                mode="repo",
                commit_sha=job.commit_sha,
                computed_at=datetime.now(tz=UTC).isoformat(),
            )
        record_bytes = canonical_json_bytes(record)
        raw_bytes = canonical_json_bytes(raw_payload)
        sha = hashlib.sha256(record_bytes).hexdigest()
        return DispatchResult(
            record_hash=record["record_hash"],
            score=record["score"],
            metrics=record["metrics"],
            spec_hash=record["spec_hash"],
            tool_digests=record["tool_digests"],
            sidecars={
                "record_sha256": f"sha256:{sha}",
                "record_bytes": str(len(record_bytes)),
                "raw_bytes": str(len(raw_bytes)),
            },
        )


def _default_clone(repo_url: str, commit_sha: str, dest: Path) -> Path:
    """Default clone helper used when no test override is supplied.

    Delegates to :func:`cce.git_ops.prepared_repo` in repo-mode.
    """
    raise DispatchError(
        "InProcessDispatcher requires a `repo_clone` callable; "
        "default cloning from a URL is not implemented in tests"
    )


__all__ = ["Dispatcher", "DispatchError", "DispatchResult", "InProcessDispatcher"]
