"""Integration tests for the ScoreService → JobConsumer → storage pipeline.

These tests exercise the path that production traffic follows end-to-end
using only in-memory fakes — no real databases, no network, no forked processes:

  ScoreService.create_score()
    → puts JobRecord on InMemoryQueue (via dispatcher=queue.put)
    → JobConsumer.run_once()
    → InProcessDispatcher.dispatch() (scores tests/fixtures/simple_python)
    → job_repo / record_repo / audit_repo updated

This is the gap left by the unit tests in test_api.py (which mock the
dispatcher entirely) and test_storage_adapters.py (which test repos in
isolation). Here all layers operate together on real data.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from cce_service.api.service import NotFound, ScoreService
from cce_service.auth.jwt import JwtVerifier, issue_hs256_token
from cce_service.dispatch.base import DispatchError, DispatchResult, InProcessDispatcher
from cce_service.storage import (
    InMemoryAuditRepo,
    InMemoryJobRepo,
    InMemoryRecordRepo,
    JobStatus,
)
from cce_service.workers.consumer import InMemoryQueue, JobConsumer

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "simple_python"
SPEC_PATH = _REPO_ROOT / "scoring-spec.yaml"

SECRET = "integration-test-secret"
COMMIT = "a" * 40


def _bearer(scopes: list[str], tenant: str = "t1") -> str:
    return "Bearer " + issue_hs256_token(
        secret=SECRET, subject="alice", tenant=tenant, scopes=scopes
    )


def _body(commit: str = COMMIT) -> dict:
    return {
        "repo_url": "https://example.test/repo.git",
        "commit_sha": commit,
        "spec_ref": "scoring-spec.yaml",
    }


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


class _Pipeline:
    """All in-memory infrastructure wired together."""

    def __init__(self) -> None:
        self.job_repo = InMemoryJobRepo()
        self.record_repo = InMemoryRecordRepo()
        self.audit_repo = InMemoryAuditRepo()
        self.queue = InMemoryQueue()

        self.service = ScoreService(
            verifier=JwtVerifier(secret=SECRET),
            job_repo=self.job_repo,
            record_repo=self.record_repo,
            audit_repo=self.audit_repo,
            dispatcher=self.queue.put,
        )

        self.consumer = JobConsumer(
            source=self.queue,
            dispatcher=InProcessDispatcher(
                spec_path=SPEC_PATH,
                repo_clone=lambda url, sha, tmp: FIXTURE_PATH,
            ),
            jobs=self.job_repo,
            records=self.record_repo,
            audits=self.audit_repo,
        )


@pytest.fixture
def pipeline() -> _Pipeline:
    return _Pipeline()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_pipeline_job_succeeds(pipeline: _Pipeline) -> None:
    view = pipeline.service.create_score(
        authz_header=_bearer(["score:write"]),
        body=_body(),
    )
    assert view.status == JobStatus.QUEUED.value
    assert view.record_hash is None

    result = pipeline.consumer.run_once(timeout=0)
    assert result is not None
    assert result.status == JobStatus.SUCCEEDED.value

    job = pipeline.job_repo.get(UUID(view.job_id))
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    assert job.record_hash is not None
    assert job.score is not None
    assert job.sidecars is not None


def test_full_pipeline_record_retrievable_after_success(pipeline: _Pipeline) -> None:
    view = pipeline.service.create_score(
        authz_header=_bearer(["score:write"]),
        body=_body(),
    )
    pipeline.consumer.run_once(timeout=0)

    job = pipeline.job_repo.get(UUID(view.job_id))
    assert job is not None and job.record_hash is not None

    record_view = pipeline.service.get_record(
        authz_header=_bearer(["records:read"]),
        record_hash=job.record_hash,
    )
    assert record_view.commit_sha == COMMIT
    assert record_view.score == job.score
    assert isinstance(record_view.metrics, dict)
    assert isinstance(record_view.tool_digests, dict)


def test_full_pipeline_audit_trail_captures_create_and_succeed(pipeline: _Pipeline) -> None:
    pipeline.service.create_score(
        authz_header=_bearer(["score:write"]),
        body=_body(),
    )
    pipeline.consumer.run_once(timeout=0)

    events = list(pipeline.audit_repo.since("1970-01-01T00:00:00+00:00"))
    actions = {e.action for e in events}
    assert "score.create" in actions
    assert "score.succeeded" in actions


# ---------------------------------------------------------------------------
# Dispatch failure path
# ---------------------------------------------------------------------------


class _FailingDispatcher:
    def dispatch(self, job) -> DispatchResult:
        raise DispatchError("simulated infra failure")


def test_full_pipeline_dispatch_failure_marks_job_failed(
    pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cce_service.retry.time.sleep", lambda _: None)

    failing_queue: InMemoryQueue = InMemoryQueue()
    failing_consumer = JobConsumer(
        source=failing_queue,
        dispatcher=_FailingDispatcher(),
        jobs=pipeline.job_repo,
        records=pipeline.record_repo,
        audits=pipeline.audit_repo,
    )
    failing_service = ScoreService(
        verifier=JwtVerifier(secret=SECRET),
        job_repo=pipeline.job_repo,
        record_repo=pipeline.record_repo,
        audit_repo=pipeline.audit_repo,
        dispatcher=failing_queue.put,
    )

    view = failing_service.create_score(
        authz_header=_bearer(["score:write"]),
        body=_body(),
    )
    result = failing_consumer.run_once(timeout=0)

    assert result is not None
    assert result.status == JobStatus.FAILED.value
    assert result.error is not None

    job = pipeline.job_repo.get(UUID(view.job_id))
    assert job is not None
    assert job.status is JobStatus.FAILED

    # Record must NOT be stored when dispatch fails
    assert pipeline.record_repo.get("sha256:" + "0" * 64) is None

    events = list(pipeline.audit_repo.since("1970-01-01T00:00:00+00:00"))
    assert any(e.action == "score.failed" for e in events)


# ---------------------------------------------------------------------------
# Tenant isolation across the full pipeline
# ---------------------------------------------------------------------------


def test_full_pipeline_tenant_isolation(pipeline: _Pipeline) -> None:
    view_alpha = pipeline.service.create_score(
        authz_header=_bearer(["score:write"], tenant="alpha"),
        body=_body(commit="a" * 40),
    )
    view_beta = pipeline.service.create_score(
        authz_header=_bearer(["score:write"], tenant="beta"),
        body=_body(commit="b" * 40),
    )

    pipeline.consumer.run_once(timeout=0)
    pipeline.consumer.run_once(timeout=0)

    job_alpha = pipeline.job_repo.get(UUID(view_alpha.job_id))
    job_beta = pipeline.job_repo.get(UUID(view_beta.job_id))
    assert job_alpha is not None and job_alpha.status is JobStatus.SUCCEEDED
    assert job_beta is not None and job_beta.status is JobStatus.SUCCEEDED

    # Alpha token cannot read beta's record
    with pytest.raises(NotFound):
        pipeline.service.get_record(
            authz_header=_bearer(["records:read"], tenant="alpha"),
            record_hash=job_beta.record_hash,
        )

    # Beta can read its own record
    record_beta = pipeline.service.get_record(
        authz_header=_bearer(["records:read"], tenant="beta"),
        record_hash=job_beta.record_hash,
    )
    assert record_beta.record_hash == job_beta.record_hash

    # Audit events are scoped per tenant
    alpha_events = list(pipeline.audit_repo.since("1970-01-01T00:00:00+00:00", tenant="alpha"))
    beta_events = list(pipeline.audit_repo.since("1970-01-01T00:00:00+00:00", tenant="beta"))
    assert alpha_events and all(e.tenant == "alpha" for e in alpha_events)
    assert beta_events and all(e.tenant == "beta" for e in beta_events)


# ---------------------------------------------------------------------------
# Score determinism: same inputs → same record_hash
# ---------------------------------------------------------------------------


def test_full_pipeline_same_inputs_same_record_hash(pipeline: _Pipeline) -> None:
    for _ in range(2):
        pipeline.service.create_score(
            authz_header=_bearer(["score:write"]),
            body=_body(),
        )

    pipeline.consumer.run_once(timeout=0)
    pipeline.consumer.run_once(timeout=0)

    jobs = pipeline.job_repo.list_for_tenant("t1")
    hashes = {j.record_hash for j in jobs}
    assert len(hashes) == 1, f"same inputs produced different hashes: {hashes}"
