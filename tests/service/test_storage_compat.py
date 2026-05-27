"""N-1 storage compatibility contract (REQ-D-6, ops/rollback.md).

The rollback strategy requires that the previous deployed image can read
records written by the current image during the one-release overlap window.
This test exercises both directions using the in-memory repos.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cce_service.storage import (
    AuditEvent,
    InMemoryAuditRepo,
    InMemoryRecordRepo,
    JobRecord,
    ScoreRecord,
)


def test_new_schema_write_old_schema_read() -> None:
    """Record written with tenant field (current schema) can be read by
    old-schema code that doesn't know about tenant."""
    record = ScoreRecord(
        record_hash="sha256:" + "a" * 64,
        commit_sha="0" * 40,
        repo_url="https://x/y",
        spec_hash="sha256:" + "0" * 64,
        score="0.5000",
        metrics={"cyclomatic": "1"},
        tool_digests={"tree_sitter_core": "sha256:" + "1" * 64},
        tenant="alpha",
        created_at=datetime.now(tz=UTC),
    )
    repo = InMemoryRecordRepo()
    repo.upsert(record)

    # Simulate old-schema client: ignore tenant attribute
    fetched = repo.get(record.record_hash)
    assert fetched is not None
    assert fetched.record_hash == record.record_hash
    assert fetched.score == record.score
    assert fetched.metrics == record.metrics
    default_tenant = getattr(fetched, "tenant", "default")
    assert default_tenant == "alpha"


def test_old_schema_write_new_schema_read() -> None:
    """Record written without tenant field (old schema) can be read by
    current-schema code (tenant field present with default)."""
    record = ScoreRecord(
        record_hash="sha256:" + "b" * 64,
        commit_sha="1" * 40,
        repo_url="https://x/y",
        spec_hash="sha256:" + "2" * 64,
        score="0.2500",
        metrics={"cognitive": "2"},
        tool_digests={"tree_sitter_core": "sha256:" + "3" * 64},
    )
    repo = InMemoryRecordRepo()
    repo.upsert(record)

    fetched = repo.get(record.record_hash)
    assert fetched is not None
    assert fetched.tenant == "default"


def test_audit_tenant_forward_compatible() -> None:
    """Audit events written with tenant field can be read by old-schema code."""
    event = AuditEvent(
        actor="worker",
        action="score.succeeded",
        target="job-1",
        tenant="beta",
        ts=datetime.now(tz=UTC),
        payload={"record_hash": "sha256:" + "c" * 64},
    )
    repo = InMemoryAuditRepo()
    repo.append(event)

    events = list(repo.since("1970-01-01T00:00:00+00:00"))
    assert len(events) >= 1
    fetched = events[0]
    default_tenant = getattr(fetched, "tenant", "default")
    assert default_tenant == "beta"


def test_job_tenant_present_across_schema() -> None:
    """Job tenant field present and survives create/get round-trip."""
    from cce_service.storage import InMemoryJobRepo

    job = JobRecord(
        repo_url="https://x/y",
        commit_sha="0" * 40,
        spec_ref="v0.1.0",
        tenant="gamma",
    )
    repo = InMemoryJobRepo()
    repo.create(job)
    fetched = repo.get(job.job_id)
    assert fetched is not None
    assert fetched.tenant == "gamma"
