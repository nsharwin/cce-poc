"""Postgres adapters for ``JobRepo`` and ``AuditRepo`` (REQ-D-1, REQ-D-5).

The adapters speak SQLAlchemy 2 and rely on Alembic migrations under
``src/cce_service/migrations/`` to create the underlying tables. They
import lazily so the deterministic scoring core (`cce`) does not pull
SQLAlchemy at import time.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from cce_service.storage.models import AuditEvent, JobRecord, JobStatus


def _require_sqlalchemy():  # pragma: no cover - import shim
    try:
        from sqlalchemy import (  # noqa: F401
            JSON,
            DateTime,
            Integer,
            String,
            create_engine,
            select,
            text,
        )
        from sqlalchemy.orm import (  # noqa: F401
            DeclarativeBase,
            Mapped,
            Session,
            mapped_column,
            sessionmaker,
        )
    except ImportError as exc:
        raise ImportError(
            "cce_service.storage.postgres requires the 'cce-service' extras. "
            "Install with: pip install '.[cce-service]'"
        ) from exc
    import sqlalchemy as sa  # noqa: F401
    from sqlalchemy.orm import (  # noqa: F811
        DeclarativeBase,
        Mapped,
        Session,
        mapped_column,
        sessionmaker,
    )

    return sa, DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def _build_orm():
    sa, DeclarativeBase, Mapped, Session, mapped_column, sessionmaker = _require_sqlalchemy()

    class Base(DeclarativeBase):
        pass

    class JobRow(Base):
        __tablename__ = "jobs"
        job_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
        tenant: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
        repo_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
        commit_sha: Mapped[str] = mapped_column(sa.String(64), nullable=False)
        spec_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
        status: Mapped[str] = mapped_column(sa.String(16), nullable=False, index=True)
        record_hash: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
        score: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
        error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
        sidecars: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
        created_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
        updated_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    class AuditRow(Base):
        __tablename__ = "audit_events"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
        actor: Mapped[str] = mapped_column(sa.String(255), nullable=False)
        action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
        target: Mapped[str] = mapped_column(sa.String(255), nullable=False)
        tenant: Mapped[str] = mapped_column(
            sa.String(255), nullable=False, default="default"
        )
        ts: Mapped[sa.DateTime] = mapped_column(
            sa.DateTime(timezone=True), nullable=False, index=True
        )
        payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    return sa, Base, JobRow, AuditRow, Session, sessionmaker


# Module-level cache so we don't re-build ORM classes on every call.
_ORM_CACHE: tuple | None = None


def _orm():
    global _ORM_CACHE
    if _ORM_CACHE is None:
        _ORM_CACHE = _build_orm()
    return _ORM_CACHE


def _job_to_row(JobRow, job: JobRecord):
    return JobRow(
        job_id=str(job.job_id),
        tenant=job.tenant,
        repo_url=job.repo_url,
        commit_sha=job.commit_sha,
        spec_ref=job.spec_ref,
        status=job.status.value,
        record_hash=job.record_hash,
        score=job.score,
        error=job.error,
        sidecars=job.sidecars,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _row_to_job(row) -> JobRecord:
    return JobRecord(
        job_id=UUID(row.job_id),
        tenant=row.tenant,
        repo_url=row.repo_url,
        commit_sha=row.commit_sha,
        spec_ref=row.spec_ref,
        status=JobStatus(row.status),
        record_hash=row.record_hash,
        score=row.score,
        error=row.error,
        sidecars=row.sidecars,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresJobRepo:
    """JobRepo backed by SQLAlchemy + Postgres."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_recycle: int | None = None,
        connect_timeout: int = 10,
    ) -> None:
        sa, _Base, JobRow, _AuditRow, Session, sessionmaker = _orm()
        self._JobRow = JobRow
        engine_kwargs: dict = {
            "future": True,
            "pool_pre_ping": True,
        }
        if pool_size is not None:
            engine_kwargs["pool_size"] = pool_size
        if max_overflow is not None:
            engine_kwargs["max_overflow"] = max_overflow
        if pool_recycle is not None:
            engine_kwargs["pool_recycle"] = pool_recycle
        self._engine = sa.create_engine(
            dsn,
            connect_args={"connect_timeout": connect_timeout},
            **engine_kwargs,
        )
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create(self, job: JobRecord) -> JobRecord:
        with self._Session.begin() as session:
            session.add(_job_to_row(self._JobRow, job))
        return job

    def get(self, job_id: UUID) -> JobRecord | None:
        with self._Session() as session:
            row = session.get(self._JobRow, str(job_id))
            return _row_to_job(row) if row else None

    def update(self, job: JobRecord) -> JobRecord:
        sa, *_ = _orm()
        with self._Session.begin() as session:
            row = session.get(self._JobRow, str(job.job_id))
            if row is None:
                raise KeyError(f"unknown job_id {job.job_id}")
            row.tenant = job.tenant
            row.repo_url = job.repo_url
            row.commit_sha = job.commit_sha
            row.spec_ref = job.spec_ref
            row.status = job.status.value
            row.record_hash = job.record_hash
            row.score = job.score
            row.error = job.error
            row.sidecars = job.sidecars
            row.updated_at = job.updated_at
        return job

    def list_for_tenant(self, tenant: str) -> list[JobRecord]:
        sa, *_ = _orm()
        with self._Session() as session:
            rows = (
                session.execute(sa.select(self._JobRow).where(self._JobRow.tenant == tenant))
                .scalars()
                .all()
            )
            return [_row_to_job(r) for r in rows]


class PostgresAuditRepo:
    """AuditRepo backed by SQLAlchemy + Postgres."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_recycle: int | None = None,
        connect_timeout: int = 10,
    ) -> None:
        sa, _Base, _JobRow, AuditRow, Session, sessionmaker = _orm()
        self._AuditRow = AuditRow
        engine_kwargs: dict = {
            "future": True,
            "pool_pre_ping": True,
        }
        if pool_size is not None:
            engine_kwargs["pool_size"] = pool_size
        if max_overflow is not None:
            engine_kwargs["max_overflow"] = max_overflow
        if pool_recycle is not None:
            engine_kwargs["pool_recycle"] = pool_recycle
        self._engine = sa.create_engine(
            dsn,
            connect_args={"connect_timeout": connect_timeout},
            **engine_kwargs,
        )
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._Session.begin() as session:
            row = self._AuditRow(
                actor=event.actor,
                action=event.action,
                target=event.target,
                tenant=event.tenant,
                ts=event.ts,
                payload=event.payload,
            )
            session.add(row)
            session.flush()
            event.id = int(row.id)
        return event

    def since(self, ts_iso: str, tenant: str | None = None) -> Iterable[AuditEvent]:
        sa, *_ = _orm()
        with self._Session() as session:
            stmt = sa.select(self._AuditRow).where(self._AuditRow.ts >= ts_iso)
            if tenant is not None:
                stmt = stmt.where(self._AuditRow.tenant == tenant)
            rows = session.execute(stmt).scalars().all()
            return [
                AuditEvent(
                    id=int(r.id),
                    actor=r.actor,
                    action=r.action,
                    target=r.target,
                    tenant=r.tenant if hasattr(r, 'tenant') else "default",
                    ts=r.ts,
                    payload=r.payload or {},
                )
                for r in rows
            ]


__all__ = ["PostgresAuditRepo", "PostgresJobRepo"]
