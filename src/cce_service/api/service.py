"""Transport-agnostic service handlers.

This module is plain Python: no FastAPI, no async. The FastAPI app
(``cce_service.api.app``) is a thin adapter that maps HTTP requests to
these methods. Doing it this way keeps the auth + storage + dispatch
logic unit-testable without a real ASGI server.

The methods raise :class:`ApiError` subclasses on auth/validation
failures; the FastAPI layer translates them to HTTP responses.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID, uuid4

from cce_service.audit import audit_event
from cce_service.auth import (
    AuthError,
    JwksVerifier,
    JwtVerifier,
    Principal,
    Scope,
    require_scope,
)
from cce_service.rate_limit import RateLimiter
from cce_service.storage import (
    AuditRepo,
    InMemoryAuditRepo,
    InMemoryJobRepo,
    InMemoryRecordRepo,
    JobRecord,
    JobRepo,
    JobStatus,
    RecordRepo,
)


class ApiError(Exception):
    status_code = 400


class Unauthorized(ApiError):
    status_code = 401


class Forbidden(ApiError):
    status_code = 403


class NotFound(ApiError):
    status_code = 404


class RateLimited(ApiError):
    status_code = 429


class BadRequest(ApiError):
    status_code = 400


@dataclass(frozen=True)
class ScoreJobView:
    job_id: str
    status: str
    record_hash: str | None
    score: str | None
    sidecars: dict[str, str] | None
    error: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreRecordView:
    record_hash: str
    commit_sha: str
    repo_url: str
    spec_hash: str
    score: str
    metrics: dict[str, Any]
    tool_digests: dict[str, str]


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOW_HTTP_REPOS = os.environ.get("CCE_ALLOW_HTTP_REPOS") == "1"
# Reject path traversal (`..`, leading `/`) and invalid characters in spec_ref.
_SAFE_SPEC_REF = re.compile(r"^[a-zA-Z0-9._\-]([/]?[a-zA-Z0-9._\-]+)*$")


class ScoreService:
    """The single object the API layer needs to call.

    Wires together: JWT verification, RBAC, rate limiting, job/record/audit
    repositories, and the future Firecracker dispatcher. The dispatcher is
    supplied as a ``Callable[[JobRecord], None]`` so tests can inject a
    fake.
    """

    def __init__(
        self,
        *,
        verifier: JwtVerifier | JwksVerifier,
        job_repo: JobRepo | None = None,
        record_repo: RecordRepo | None = None,
        audit_repo: AuditRepo | None = None,
        rate_limiter: RateLimiter | None = None,
        dispatcher: Any = None,
    ) -> None:
        self._verifier = verifier
        self.jobs = job_repo or InMemoryJobRepo()
        self.records = record_repo or InMemoryRecordRepo()
        self.audits = audit_repo or InMemoryAuditRepo()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.dispatcher = dispatcher

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _principal(self, authz_header: str | None) -> Principal:
        if not authz_header or not authz_header.lower().startswith("bearer "):
            raise Unauthorized("missing bearer token")
        token = authz_header.split(None, 1)[1]
        try:
            return self._verifier.verify(token)
        except AuthError as exc:
            raise Unauthorized(str(exc)) from exc

    def _check_scope(self, principal: Principal, scope: Scope) -> None:
        try:
            require_scope(principal, scope)
        except AuthError as exc:
            raise Forbidden(str(exc)) from exc

    def _check_rate(self, principal: Principal, bucket: str) -> None:
        if not self.rate_limiter.allow(principal.tenant, bucket):
            raise RateLimited("rate limit exceeded")

    # ------------------------------------------------------------------
    # POST /v1/scores
    # ------------------------------------------------------------------

    def create_score(
        self,
        *,
        authz_header: str | None,
        body: dict[str, Any],
    ) -> ScoreJobView:
        principal = self._principal(authz_header)
        self._check_scope(principal, Scope.SCORE_WRITE)
        self._check_rate(principal, "score")

        repo_url = body.get("repo_url")
        commit_sha = body.get("commit_sha")
        spec_ref = body.get("spec_ref")
        _allowed_schemes = ("https://", "http://") if _ALLOW_HTTP_REPOS else ("https://",)
        if not isinstance(repo_url, str) or not repo_url.startswith(_allowed_schemes):
            raise BadRequest("repo_url must be an https:// URL" + (
                " (http:// allowed by CCE_ALLOW_HTTP_REPOS)" if _ALLOW_HTTP_REPOS else ""
            ))
        if not isinstance(commit_sha, str) or not _SHA40.match(commit_sha):
            raise BadRequest("commit_sha must be a 40-char lowercase hex SHA")
        if not isinstance(spec_ref, str) or not spec_ref:
            raise BadRequest("spec_ref is required")
        if ".." in spec_ref or spec_ref.startswith("/") or not _SAFE_SPEC_REF.match(spec_ref):
            raise BadRequest("spec_ref must not contain path traversal")

        job = JobRecord(
            job_id=uuid4(),
            tenant=principal.tenant,
            repo_url=repo_url,
            commit_sha=commit_sha,
            spec_ref=spec_ref,
            status=JobStatus.QUEUED,
        )
        self.jobs.create(job)
        self.audits.append(
            audit_event(
                actor=principal.subject,
                action="score.create",
                target=str(job.job_id),
                tenant=principal.tenant,
                payload={"repo_url": repo_url, "commit_sha": commit_sha},
            )
        )
        if self.dispatcher is not None:
            self.dispatcher(job)
        return _view_job(job)

    # ------------------------------------------------------------------
    # GET /v1/scores/{job_id}
    # ------------------------------------------------------------------

    def get_score(
        self,
        *,
        authz_header: str | None,
        job_id: str,
    ) -> ScoreJobView:
        principal = self._principal(authz_header)
        self._check_scope(principal, Scope.SCORE_WRITE)
        try:
            uid = UUID(job_id)
        except ValueError as exc:
            raise BadRequest("job_id must be a UUID") from exc
        job = self.jobs.get(uid)
        if job is None or job.tenant != principal.tenant:
            raise NotFound("unknown job")
        return _view_job(job)

    # ------------------------------------------------------------------
    # GET /v1/records/{record_hash}
    # ------------------------------------------------------------------

    def get_record(
        self,
        *,
        authz_header: str | None,
        record_hash: str,
    ) -> ScoreRecordView:
        principal = self._principal(authz_header)
        self._check_scope(principal, Scope.RECORDS_READ)
        if not _SHA_HASH.match(record_hash):
            raise BadRequest("record_hash must be sha256:<64 hex>")
        record = self.records.get(record_hash)
        if record is None or record.tenant != principal.tenant:
            raise NotFound("unknown record")
        return ScoreRecordView(
            record_hash=record.record_hash,
            commit_sha=record.commit_sha,
            repo_url=record.repo_url,
            spec_hash=record.spec_hash,
            score=record.score,
            metrics=dict(record.metrics),
            tool_digests=dict(record.tool_digests),
        )

    # ------------------------------------------------------------------
    # GET /v1/audit?since=...
    # ------------------------------------------------------------------

    def list_audit(
        self,
        *,
        authz_header: str | None,
        since_iso: str,
    ) -> list[dict[str, Any]]:
        principal = self._principal(authz_header)
        self._check_scope(principal, Scope.AUDIT_READ)
        events = self.audits.since(since_iso, tenant=principal.tenant)
        return [
            {
                "id": e.id,
                "actor": e.actor,
                "action": e.action,
                "target": e.target,
                "tenant": e.tenant,
                "ts": e.ts.isoformat(),
                "payload": e.payload,
            }
            for e in events
        ]


def _view_job(job: JobRecord) -> ScoreJobView:
    return ScoreJobView(
        job_id=str(job.job_id),
        status=job.status.value,
        record_hash=job.record_hash,
        score=job.score,
        sidecars=job.sidecars,
        error=job.error,
    )


__all__ = [
    "ApiError",
    "BadRequest",
    "Forbidden",
    "NotFound",
    "RateLimited",
    "ScoreJobView",
    "ScoreRecordView",
    "ScoreService",
    "Unauthorized",
]
