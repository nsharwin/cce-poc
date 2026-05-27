"""FastAPI ASGI-level tests for ``cce_service.api.app.build_app``.

Specifically exercises the body-size-limit middleware against streamed
bodies that omit (or forge) ``Content-Length`` — a header-only check
would let such bodies through and risk memory exhaustion in
``await request.json()``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cce_service.api.app import build_app
from cce_service.api.service import ScoreService
from cce_service.auth.jwt import JwtVerifier


def _build_test_client() -> TestClient:
    svc = ScoreService(verifier=JwtVerifier(secret="test"))
    return TestClient(build_app(svc), raise_server_exceptions=False)


def test_body_size_limit_rejects_chunked_overflow() -> None:
    client = _build_test_client()
    big = b"x" * (2 * 1024 * 1024)

    def gen():
        yield big

    r = client.post(
        "/v1/scores",
        content=gen(),
        headers={"Authorization": "Bearer junk"},
    )
    assert r.status_code == 413, r.text


def test_body_size_limit_allows_small_body() -> None:
    client = _build_test_client()
    r = client.post(
        "/v1/scores",
        json={"hello": "world"},
        headers={"Authorization": "Bearer junk"},
    )
    # Auth/validation may reject (401/400), but not 413.
    assert r.status_code != 413, r.text


def test_metrics_requires_token(monkeypatch):
    monkeypatch.setenv("CCE_ENV", "production")
    monkeypatch.setenv("CCE_METRICS_TOKEN", "s3cret")
    client = _build_test_client()
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert b"# HELP" in ok.content or b"# TYPE" in ok.content


def test_metrics_503_without_token_in_prod(monkeypatch):
    monkeypatch.setenv("CCE_ENV", "production")
    monkeypatch.delenv("CCE_METRICS_TOKEN", raising=False)
    client = _build_test_client()
    assert client.get("/metrics").status_code == 503


def test_metrics_open_in_development(monkeypatch):
    monkeypatch.setenv("CCE_ENV", "development")
    monkeypatch.delenv("CCE_METRICS_TOKEN", raising=False)
    client = _build_test_client()
    assert client.get("/metrics").status_code == 200
