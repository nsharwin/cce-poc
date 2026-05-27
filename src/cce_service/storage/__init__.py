"""Storage interfaces and an in-memory implementation for tests/dev.

The Postgres and ClickHouse backends are imported lazily so the POC dev
environment does not need either driver installed.
"""

from cce_service.storage.models import (
    AuditEvent,
    JobRecord,
    JobStatus,
    ScoreRecord,
)
from cce_service.storage.repos import (
    AuditRepo,
    InMemoryAuditRepo,
    InMemoryJobRepo,
    InMemoryRecordRepo,
    JobRepo,
    RecordRepo,
)

__all__ = [
    "AuditEvent",
    "AuditRepo",
    "InMemoryAuditRepo",
    "InMemoryJobRepo",
    "InMemoryRecordRepo",
    "JobRecord",
    "JobRepo",
    "JobStatus",
    "RecordRepo",
    "ScoreRecord",
]
