"""Repository Protocols and an in-memory backend for tests/dev.

The Postgres adapter (``cce_service.storage.postgres``) and ClickHouse
adapter (``cce_service.storage.clickhouse``) implement the same Protocols
so the API layer is database-agnostic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from cce_service.storage.models import AuditEvent, JobRecord, ScoreRecord


class JobRepo(Protocol):
    def create(self, job: JobRecord) -> JobRecord: ...
    def get(self, job_id: UUID) -> JobRecord | None: ...
    def update(self, job: JobRecord) -> JobRecord: ...
    def list_for_tenant(self, tenant: str) -> list[JobRecord]: ...


class RecordRepo(Protocol):
    def upsert(self, record: ScoreRecord) -> None: ...
    def get(self, record_hash: str) -> ScoreRecord | None: ...


class AuditRepo(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent: ...
    def since(self, ts_iso: str, tenant: str | None = None) -> Iterable[AuditEvent]: ...


# ---------------------------------------------------------------------------
# In-memory implementations
# ---------------------------------------------------------------------------


class InMemoryJobRepo:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[UUID, JobRecord] = {}

    def create(self, job: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: UUID) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: JobRecord) -> JobRecord:
        with self._lock:
            if job.job_id not in self._jobs:
                raise KeyError(f"unknown job_id {job.job_id}")
            self._jobs[job.job_id] = job
        return job

    def list_for_tenant(self, tenant: str) -> list[JobRecord]:
        with self._lock:
            return [j for j in self._jobs.values() if j.tenant == tenant]


class InMemoryRecordRepo:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, ScoreRecord] = {}

    def upsert(self, record: ScoreRecord) -> None:
        with self._lock:
            self._records[record.record_hash] = record

    def get(self, record_hash: str) -> ScoreRecord | None:
        with self._lock:
            return self._records.get(record_hash)


class InMemoryAuditRepo:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []
        self._next_id = 1

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._lock:
            event.id = self._next_id
            self._next_id += 1
            self._events.append(event)
        return event

    def since(self, ts_iso: str, tenant: str | None = None) -> Iterable[AuditEvent]:
        with self._lock:
            events = [e for e in self._events if e.ts.isoformat() >= ts_iso]
            if tenant is not None:
                events = [e for e in events if e.tenant == tenant]
            return events


__all__ = [
    "AuditRepo",
    "InMemoryAuditRepo",
    "InMemoryJobRepo",
    "InMemoryRecordRepo",
    "JobRepo",
    "RecordRepo",
]
