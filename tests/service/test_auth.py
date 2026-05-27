"""Auth tests for the stdlib HS256 verifier."""

from __future__ import annotations

import time

import pytest

from cce_service.auth import AuthError, JwtVerifier, Scope, issue_hs256_token, require_scope
from cce_service.auth.jwt import Principal

SECRET = "test-secret-do-not-use-in-prod"


def _token(scopes: list[str] | None = None, **overrides: object) -> str:
    if scopes is None:
        scopes = ["score:write"]
    return issue_hs256_token(
        secret=SECRET, subject="alice", tenant="t1", scopes=scopes, **overrides
    )


def test_verifier_accepts_valid_token() -> None:
    verifier = JwtVerifier(secret=SECRET)
    principal = verifier.verify(_token())
    assert principal.subject == "alice"
    assert principal.tenant == "t1"
    assert "score:write" in principal.scopes


def test_verifier_rejects_bad_signature() -> None:
    verifier = JwtVerifier(secret=SECRET)
    other = issue_hs256_token(
        secret="not-the-same", subject="alice", tenant="t1", scopes=["score:write"]
    )
    with pytest.raises(AuthError):
        verifier.verify(other)


def test_verifier_rejects_expired_token() -> None:
    verifier = JwtVerifier(secret=SECRET)
    token = _token(ttl_seconds=1, now=int(time.time()) - 3600)
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_verifier_rejects_issuer_mismatch() -> None:
    verifier = JwtVerifier(secret=SECRET, issuer="cce-prod")
    with pytest.raises(AuthError):
        verifier.verify(_token())


def test_verifier_rejects_malformed_token() -> None:
    verifier = JwtVerifier(secret=SECRET)
    with pytest.raises(AuthError):
        verifier.verify("not.a.jwt")
    with pytest.raises(AuthError):
        verifier.verify("only-one-part")


def test_require_scope_allows_present() -> None:
    p = Principal(subject="a", tenant="t", scopes=frozenset({"score:write"}), expires_at=0)
    require_scope(p, Scope.SCORE_WRITE)  # does not raise


def test_require_scope_rejects_missing() -> None:
    p = Principal(subject="a", tenant="t", scopes=frozenset({"records:read"}), expires_at=0)
    with pytest.raises(AuthError):
        require_scope(p, Scope.SCORE_WRITE)


def test_hs256_rejected_when_ccereject_hs256_set(monkeypatch) -> None:
    monkeypatch.setenv("CCE_REJECT_HS256", "1")
    with pytest.raises(RuntimeError, match="CCE_REJECT_HS256"):
        JwtVerifier(secret=SECRET)


def test_jwks_verifier_refuses_init_without_crypto_outside_dev(monkeypatch):
    """JwksVerifier MUST refuse to construct unless CCE_ENV=development when
    the cryptography library is unavailable. Hash-only mode is no longer a
    silent fallback."""
    import cce_service.auth.jwks as jwks_mod
    monkeypatch.setattr(jwks_mod, "_HAS_CRYPTO", False)
    monkeypatch.setenv("CCE_ENV", "production")
    with pytest.raises(RuntimeError, match="cryptography"):
        jwks_mod.JwksVerifier(
            jwks_uri="https://example.invalid/jwks.json",
            issuer="iss", audience="aud",
        )


def test_jwks_verifier_allows_dev_without_crypto(monkeypatch):
    """In CCE_ENV=development the verifier may start without crypto for local
    fixtures, but signature verification must hard-fail."""
    import cce_service.auth.jwks as jwks_mod
    monkeypatch.setattr(jwks_mod, "_HAS_CRYPTO", False)
    monkeypatch.setenv("CCE_ENV", "development")
    v = jwks_mod.JwksVerifier(
        jwks_uri="https://example.invalid/jwks.json",
        issuer="iss", audience="aud",
    )
    assert isinstance(v, jwks_mod.JwksVerifier)
    # Signature verification must raise AuthError, not silently return.
    with pytest.raises(jwks_mod.AuthError, match="signature verification unavailable"):
        jwks_mod._verify_rs256(b"x.y", b"sig", {"e": "AQAB", "n": "AA"})
