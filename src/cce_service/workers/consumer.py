"""Job queue consumer.

The production deployment uses Redis Streams; the abstract ``JobSource``
protocol below is implemented by both the Redis adapter (not included
in this POC tree) and by ``InMemoryQueue`` (used by tests).

The consumer is intentionally synchronous so it can be unit-tested
deterministically. Production wraps each call in an asyncio task with a
``wallclock_seconds`` hard cap from :class:`FirecrackerConfig`.
"""

from __future__ import annotations

import logging
import queue
from datetime import UTC, datetime
from typing import Protocol

from cce.otel import CIRCUIT_BREAKER_STATE, JOB_FAILURES_TOTAL, QUEUE_DEPTH, RECORDS_TOTAL
from cce_service.audit import audit_event
from cce_service.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from cce_service.dispatch import Dispatcher, DispatchError
from cce_service.logging_setup import JobLogAdapter, setup_json_logging
from cce_service.retry import RetryExhaustedError, retry_on_transient_error
from cce_service.storage import (
    AuditRepo,
    JobRecord,
    JobRepo,
    JobStatus,
    RecordRepo,
    ScoreRecord,
)

_logger = logging.getLogger("cce_service.workers.consumer")


class JobSource(Protocol):
    def get(self, timeout: float | None = None) -> JobRecord | None: ...
    def put(self, job: JobRecord) -> None: ...
    def size(self) -> int: ...


class InMemoryQueue:
    """``queue.Queue``-backed source for tests and single-node dev."""

    def __init__(self) -> None:
        self._q: queue.Queue[JobRecord] = queue.Queue()

    def put(self, job: JobRecord) -> None:
        self._q.put(job)

    def get(self, timeout: float | None = None) -> JobRecord | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._q.qsize()


class JobConsumer:
    """Pulls jobs from the queue, dispatches, persists results."""

    def __init__(
        self,
        *,
        source: JobSource,
        dispatcher: Dispatcher,
        jobs: JobRepo,
        records: RecordRepo,
        audits: AuditRepo,
        dispatch_circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        setup_json_logging()
        self.source = source
        self.dispatcher = dispatcher
        self.jobs = jobs
        self.records = records
        self.audits = audits
        self.dispatch_cb = dispatch_circuit_breaker or CircuitBreaker(
            name="dispatch", failure_threshold=5, recovery_timeout=30.0
        )
        self._logger = JobLogAdapter(_logger, {})

    def run_once(self, timeout: float = 0.1) -> JobRecord | None:
        """Process at most one job. Returns the (updated) job or ``None``."""
        QUEUE_DEPTH.set(self.source.size())
        _emit_cb_state(self.dispatch_cb)
        job = self.source.get(timeout=timeout)
        if job is None:
            return None
        QUEUE_DEPTH.dec()
        return self._process(job)

    def _process(self, job: JobRecord) -> JobRecord:
        self._logger.extra["job_id"] = str(job.job_id)
        job.status = JobStatus.RUNNING
        job.updated_at = datetime.now(tz=UTC)
        self.jobs.update(job)
        try:
            _dispatch = retry_on_transient_error(
                max_attempts=3,
                base_delay=1.0,
                max_delay=4.0,
                retryable_exceptions=(DispatchError,),
                component="dispatch",
            )(self.dispatcher.dispatch)
            result = self.dispatch_cb.call(_dispatch, job)
        except CircuitBreakerOpenError as exc:
            _logger.warning("dispatch circuit breaker open, requeuing job %s", job.job_id)
            job.error = str(exc)
            job.updated_at = datetime.now(tz=UTC)
            self.jobs.update(job)
            self.source.put(job)
            return job
        except RetryExhaustedError as exc:
            JOB_FAILURES_TOTAL.labels(reason="retry_exhausted").inc()
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.updated_at = datetime.now(tz=UTC)
            self.jobs.update(job)
            self.audits.append(
                audit_event(
                    actor="worker",
                    action="score.failed",
                    target=str(job.job_id),
                    tenant=job.tenant,
                    payload={"reason": "retry_exhausted", "error": str(exc)},
                )
            )
            return job
        except DispatchError as exc:
            JOB_FAILURES_TOTAL.labels(reason="dispatch").inc()
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.updated_at = datetime.now(tz=UTC)
            self.jobs.update(job)
            self.audits.append(
                audit_event(
                    actor="worker",
                    action="score.failed",
                    target=str(job.job_id),
                    tenant=job.tenant,
                    payload={"reason": "dispatch", "error": str(exc)},
                )
            )
            return job
        except Exception as exc:  # noqa: BLE001 — bound-catch is intentional
            JOB_FAILURES_TOTAL.labels(reason="unexpected").inc()
            job.status = JobStatus.FAILED
            job.error = f"unexpected: {exc!r}"
            job.updated_at = datetime.now(tz=UTC)
            self.jobs.update(job)
            _logger.exception("unexpected dispatch failure for job %s", job.job_id)
            return job

        # Persist result + ClickHouse record + audit + counters.
        self.records.upsert(
            ScoreRecord(
                record_hash=result.record_hash,
                commit_sha=job.commit_sha,
                repo_url=job.repo_url,
                spec_hash=result.spec_hash,
                score=result.score,
                metrics=dict(result.metrics),
                tool_digests=dict(result.tool_digests),
                tenant=job.tenant,
            )
        )
        job.status = JobStatus.SUCCEEDED
        job.record_hash = result.record_hash
        job.score = result.score
        job.sidecars = dict(result.sidecars)
        job.error = None
        job.updated_at = datetime.now(tz=UTC)
        self.jobs.update(job)
        self.audits.append(
            audit_event(
                actor="worker",
                action="score.succeeded",
                target=str(job.job_id),
                tenant=job.tenant,
                payload={"record_hash": result.record_hash},
            )
        )
        RECORDS_TOTAL.inc()
        return job


def _emit_cb_state(cb: CircuitBreaker) -> None:
    state_map = {"closed": 0, "half_open": 1, "open": 2}
    CIRCUIT_BREAKER_STATE.labels(name=cb.name).set(state_map.get(cb.state, -1))


__all__ = ["InMemoryQueue", "JobConsumer", "JobSource"]
