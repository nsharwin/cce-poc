"""Domain models for the production service.

These dataclasses are stdlib-only so they are safe to import from any
process (CLI, worker, tests) without pulling SQLAlchemy or the
ClickHouse driver. The Postgres and ClickHouse adapters map them to
their respective row types.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobRecord:
    """Lifecycle row in Postgres ``jobs`` table."""

    job_id: UUID = field(default_factory=uuid4)
    tenant: str = "default"
    repo_url: str = ""
    commit_sha: str = ""
    spec_ref: str = ""
    status: JobStatus = JobStatus.QUEUED
    record_hash: str | None = None
    score: str | None = None  # canonical decimal string
    error: str | None = None
    sidecars: dict[str, str] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class ScoreRecord:
    """Row in ClickHouse ``records`` table (REQ-D-2)."""

    record_hash: str
    commit_sha: str
    repo_url: str
    spec_hash: str
    score: str
    metrics: dict[str, Any]
    tool_digests: dict[str, str]
    tenant: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class AuditEvent:
    """Row in Postgres ``audit_events`` table (REQ-D-5)."""

    id: int = 0
    actor: str = ""
    action: str = ""
    target: str = ""
    tenant: str = "default"
    ts: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    payload: dict[str, Any] = field(default_factory=dict)


__all__ = ["AuditEvent", "JobRecord", "JobStatus", "ScoreRecord"]
