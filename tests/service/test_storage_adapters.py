"""Adapter contract smoke against the in-memory implementations.

Real Postgres + ClickHouse coverage is exercised by `ops/staging/smoke.sh`
against the docker-compose stack; here we only assert that the three
repository Protocols round-trip the canonical domain models correctly.
This keeps `uv run pytest -q` fast and dependency-free on macOS/dev.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cce_service.storage.models import AuditEvent, JobRecord, JobStatus, ScoreRecord
from cce_service.storage.repos import (
    InMemoryAuditRepo,
    InMemoryJobRepo,
    InMemoryRecordRepo,
)


def test_job_repo_create_get_update_list() -> None:
    repo = InMemoryJobRepo()
    job = JobRecord(
        repo_url="https://example.test/repo.git",
        commit_sha="deadbeef" * 5,
        spec_ref="./scoring-spec.yaml",
        tenant="acme",
    )
    repo.create(job)
    fetched = repo.get(job.job_id)
    assert fetched is not None
    assert fetched.repo_url == job.repo_url
    assert fetched.status is JobStatus.QUEUED

    fetched.status = JobStatus.SUCCEEDED
    fetched.record_hash = "sha256:" + "0" * 64
    fetched.score = "0.7500"
    repo.update(fetched)

    again = repo.get(job.job_id)
    assert again is not None
    assert again.status is JobStatus.SUCCEEDED
    assert again.record_hash == "sha256:" + "0" * 64

    assert [j.job_id for j in repo.list_for_tenant("acme")] == [job.job_id]
    assert repo.list_for_tenant("nope") == []


def test_record_repo_upsert_idempotent() -> None:
    repo = InMemoryRecordRepo()
    record = ScoreRecord(
        record_hash="sha256:" + "a" * 64,
        commit_sha="c" * 40,
        repo_url="https://example.test/repo.git",
        spec_hash="sha256:" + "b" * 64,
        score="0.5000",
        metrics={"cyclomatic": "0.5"},
        tool_digests={"lizard": "sha256:" + "1" * 64},
    )
    repo.upsert(record)
    repo.upsert(record)  # idempotent
    out = repo.get(record.record_hash)
    assert out is not None
    assert out.score == "0.5000"
    assert out.metrics == {"cyclomatic": "0.5"}
    assert repo.get("sha256:" + "9" * 64) is None


def test_audit_repo_append_and_since() -> None:
    repo = InMemoryAuditRepo()
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 6, 1, tzinfo=UTC)

    a = repo.append(AuditEvent(actor="alice", action="score.create", target="job:1", ts=early))
    b = repo.append(AuditEvent(actor="bob", action="score.create", target="job:2", ts=late))

    assert a.id != b.id  # ids monotonically increase
    after = list(repo.since("2026-03-01T00:00:00+00:00"))
    assert [e.actor for e in after] == ["bob"]


def test_adapter_modules_import_lazily() -> None:
    """The Postgres/ClickHouse adapter modules must be importable on macOS/dev
    without the `cce-service` extras installed. Constructors will raise
    ImportError when actually invoked — that's the contract."""
    from cce_service.storage import clickhouse, postgres  # noqa: F401
    assert hasattr(postgres, "PostgresJobRepo")
    assert hasattr(postgres, "PostgresAuditRepo")
    assert hasattr(clickhouse, "ClickHouseRecordRepo")
