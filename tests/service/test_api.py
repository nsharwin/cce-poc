"""End-to-end ScoreService tests without a real ASGI server.

Exercises the same handlers that ``cce_service.api.app.build_app`` binds
to FastAPI, plus the 401/403/429 error paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cce_service.api import (
    Forbidden,
    ScoreService,
    Unauthorized,
)
from cce_service.api.service import BadRequest, NotFound, RateLimited
from cce_service.auth import JwtVerifier, issue_hs256_token
from cce_service.storage import JobStatus, ScoreRecord

SECRET = "test-secret"
COMMIT = "0" * 40
RECORD_HASH = "sha256:" + ("a" * 64)


def _bearer(scopes: list[str], tenant: str = "t1") -> str:
    return "Bearer " + issue_hs256_token(
        secret=SECRET, subject="alice", tenant=tenant, scopes=scopes
    )


@pytest.fixture
def service() -> ScoreService:
    return ScoreService(verifier=JwtVerifier(secret=SECRET))


def _valid_body() -> dict:
    return {
        "repo_url": "https://github.com/example/repo.git",
        "commit_sha": COMMIT,
        "spec_ref": "v0.1.0",
    }


def test_create_score_happy_path(service: ScoreService) -> None:
    view = service.create_score(
        authz_header=_bearer(["score:write"]),
        body=_valid_body(),
    )
    assert view.status == JobStatus.QUEUED.value
    assert view.record_hash is None

    got = service.get_score(
        authz_header=_bearer(["score:write"]), job_id=view.job_id
    )
    assert got.job_id == view.job_id


def test_missing_auth_returns_401(service: ScoreService) -> None:
    with pytest.raises(Unauthorized):
        service.create_score(authz_header=None, body=_valid_body())
    with pytest.raises(Unauthorized):
        service.create_score(authz_header="Token abc", body=_valid_body())


def test_wrong_scope_returns_403(service: ScoreService) -> None:
    with pytest.raises(Forbidden):
        service.create_score(
            authz_header=_bearer(["records:read"]),
            body=_valid_body(),
        )


def test_invalid_body_returns_400(service: ScoreService) -> None:
    with pytest.raises(BadRequest):
        service.create_score(
            authz_header=_bearer(["score:write"]),
            body={"repo_url": "not-a-url", "commit_sha": COMMIT, "spec_ref": "v"},
        )
    with pytest.raises(BadRequest):
        service.create_score(
            authz_header=_bearer(["score:write"]),
            body={
                "repo_url": "https://x/y",
                "commit_sha": "deadbeef",
                "spec_ref": "v",
            },
        )


def test_rate_limit_triggers_429(service: ScoreService) -> None:
    body = _valid_body()
    auth = _bearer(["score:write"])
    # Default 'score' bucket capacity is 10 -> 11th must 429.
    for _ in range(10):
        service.create_score(authz_header=auth, body=body)
    with pytest.raises(RateLimited):
        service.create_score(authz_header=auth, body=body)


def test_tenant_isolation_blocks_cross_tenant_read(service: ScoreService) -> None:
    view = service.create_score(
        authz_header=_bearer(["score:write"], tenant="alpha"),
        body=_valid_body(),
    )
    with pytest.raises(NotFound):
        service.get_score(
            authz_header=_bearer(["score:write"], tenant="beta"),
            job_id=view.job_id,
        )


def test_records_lookup(service: ScoreService) -> None:
    service.records.upsert(
        ScoreRecord(
            record_hash=RECORD_HASH,
            commit_sha=COMMIT,
            repo_url="https://x/y",
            spec_hash="sha256:" + "0" * 64,
            score="0.8300",
            metrics={"cyclomatic": "1"},
            tool_digests={"lizard": "sha256:" + "5" * 64},
            tenant="t1",
            created_at=datetime.now(tz=UTC),
        )
    )
    view = service.get_record(
        authz_header=_bearer(["records:read"]), record_hash=RECORD_HASH
    )
    assert view.record_hash == RECORD_HASH
    assert view.metrics == {"cyclomatic": "1"}


def test_records_lookup_unknown_returns_404(service: ScoreService) -> None:
    with pytest.raises(NotFound):
        service.get_record(
            authz_header=_bearer(["records:read"]), record_hash=RECORD_HASH
        )


def test_records_lookup_rejects_bad_hash(service: ScoreService) -> None:
    with pytest.raises(BadRequest):
        service.get_record(
            authz_header=_bearer(["records:read"]), record_hash="not-a-hash"
        )


def test_record_tenant_isolation_blocks_cross_tenant_read(service: ScoreService) -> None:
    service.records.upsert(
        ScoreRecord(
            record_hash=RECORD_HASH,
            commit_sha=COMMIT,
            repo_url="https://x/y",
            spec_hash="sha256:" + "0" * 64,
            score="0.8300",
            metrics={"cyclomatic": "1"},
            tool_digests={"lizard": "sha256:" + "5" * 64},
            tenant="alpha",
            created_at=datetime.now(tz=UTC),
        )
    )
    with pytest.raises(NotFound):
        service.get_record(
            authz_header=_bearer(["records:read"], tenant="beta"),
            record_hash=RECORD_HASH,
        )


def test_record_tenant_isolation_allows_same_tenant_read(service: ScoreService) -> None:
    service.records.upsert(
        ScoreRecord(
            record_hash=RECORD_HASH,
            commit_sha=COMMIT,
            repo_url="https://x/y",
            spec_hash="sha256:" + "0" * 64,
            score="0.8300",
            metrics={"cyclomatic": "1"},
            tool_digests={"lizard": "sha256:" + "5" * 64},
            tenant="alpha",
            created_at=datetime.now(tz=UTC),
        )
    )
    view = service.get_record(
        authz_header=_bearer(["records:read"], tenant="alpha"),
        record_hash=RECORD_HASH,
    )
    assert view.record_hash == RECORD_HASH


def test_audit_endpoint_requires_audit_scope(service: ScoreService) -> None:
    with pytest.raises(Forbidden):
        service.list_audit(
            authz_header=_bearer(["score:write"]),
            since_iso="1970-01-01T00:00:00+00:00",
        )


def test_audit_endpoint_returns_create_events(service: ScoreService) -> None:
    service.create_score(authz_header=_bearer(["score:write"]), body=_valid_body())
    events = service.list_audit(
        authz_header=_bearer(["audit:read"]),
        since_iso="1970-01-01T00:00:00+00:00",
    )
    assert any(e["action"] == "score.create" for e in events)


def test_audit_tenant_isolation_blocks_cross_tenant_read(service: ScoreService) -> None:
    service.create_score(
        authz_header=_bearer(["score:write"], tenant="alpha"),
        body=_valid_body(),
    )
    service.create_score(
        authz_header=_bearer(["score:write"], tenant="beta"),
        body=_valid_body(),
    )
    alpha_events = service.list_audit(
        authz_header=_bearer(["audit:read"], tenant="alpha"),
        since_iso="1970-01-01T00:00:00+00:00",
    )
    beta_events = service.list_audit(
        authz_header=_bearer(["audit:read"], tenant="beta"),
        since_iso="1970-01-01T00:00:00+00:00",
    )
    assert all(e["tenant"] == "alpha" for e in alpha_events)
    assert all(e["tenant"] == "beta" for e in beta_events)
    alpha_actions = {e["action"] for e in alpha_events}
    beta_actions = {e["action"] for e in beta_events}
    assert "score.create" in alpha_actions
    assert "score.create" in beta_actions


def test_dispatcher_called_on_create() -> None:
    seen: list[str] = []
    svc = ScoreService(
        verifier=JwtVerifier(secret=SECRET),
        dispatcher=lambda job: seen.append(str(job.job_id)),
    )
    view = svc.create_score(
        authz_header=_bearer(["score:write"]), body=_valid_body()
    )
    assert seen == [view.job_id]
