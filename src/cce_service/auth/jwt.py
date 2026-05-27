"""Stdlib-only HS256 JWT verifier for tests/dev.

Production uses a JWKS-based verifier (RS256/ES256); the public surface
(:class:`JwtVerifier`, :class:`Principal`) is identical so swapping is
configuration-only.

This file is auth-critical — every helper is constant-time where it
matters and tokens carry an explicit ``exp``/``iat``/``aud`` set.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import time
from collections.abc import Iterable


class AuthError(Exception):
    """Raised on any token-validation failure. Maps to HTTP 401."""


@dataclasses.dataclass(frozen=True)
class Principal:
    """Authenticated identity extracted from a verified JWT."""

    subject: str
    tenant: str
    scopes: frozenset[str]
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_hs256_token(
    *,
    secret: str,
    subject: str,
    tenant: str,
    scopes: Iterable[str],
    issuer: str = "cce-test",
    audience: str = "cce-api",
    ttl_seconds: int = 300,
    now: int | None = None,
) -> str:
    """Mint a signed HS256 JWT. Used by tests and the dev-mode CLI."""
    now_s = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "tenant": tenant,
        "scopes": sorted(scopes),
        "iat": now_s,
        "exp": now_s + ttl_seconds,
    }
    header_b = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b}.{payload_b}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b}.{payload_b}.{_b64url_encode(sig)}"


def _warn_if_hs256_in_prod() -> None:
    env = os.environ.get("CCE_ENV", "").strip().lower()
    if env == "development":
        return
    import logging
    logger = logging.getLogger("cce_service.auth.jwt")
    if os.environ.get("CCE_ALLOW_HS256") == "1":
        logger.critical(
            "HS256 JwtVerifier active in env=%r via CCE_ALLOW_HS256=1 — "
            "use JWKS (RS256/ES256) for production traffic.", env or "<unset>",
        )
        return
    raise RuntimeError(
        f"HS256 JwtVerifier is not allowed in env={env or '<unset>'!r}. "
        "Use JwksVerifier (RS256/ES256) or set CCE_ALLOW_HS256=1 explicitly."
    )


class JwtVerifier:
    """Validates HS256 tokens signed with a configured shared secret."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str = "cce-test",
        audience: str = "cce-api",
        leeway_seconds: int = 0,
    ) -> None:
        if not secret:
            raise ValueError("HS256 verifier requires a non-empty secret")
        _warn_if_hs256_in_prod()
        self._secret = secret.encode()
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds

    def verify(self, token: str, *, now: int | None = None) -> Principal:
        try:
            header_b, payload_b, sig_b = token.split(".")
        except ValueError as exc:
            raise AuthError("malformed token") from exc

        try:
            header = json.loads(_b64url_decode(header_b))
            payload = json.loads(_b64url_decode(payload_b))
            signature = _b64url_decode(sig_b)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError("malformed token") from exc

        if header.get("alg") != "HS256" or header.get("typ") not in {"JWT", None}:
            raise AuthError("unsupported alg")

        expected_sig = hmac.new(
            self._secret, f"{header_b}.{payload_b}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_sig):
            raise AuthError("bad signature")

        if payload.get("iss") != self._issuer:
            raise AuthError("issuer mismatch")
        if payload.get("aud") != self._audience:
            raise AuthError("audience mismatch")

        now_s = int(time.time()) if now is None else now
        exp = int(payload.get("exp", 0))
        if exp + self._leeway < now_s:
            raise AuthError("token expired")

        subject = payload.get("sub")
        tenant = payload.get("tenant")
        scopes = payload.get("scopes", [])
        if not isinstance(subject, str) or not isinstance(tenant, str):
            raise AuthError("missing subject/tenant")
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise AuthError("invalid scopes claim")

        return Principal(
            subject=subject,
            tenant=tenant,
            scopes=frozenset(scopes),
            expires_at=exp,
        )


__all__ = ["AuthError", "JwtVerifier", "Principal", "issue_hs256_token"]
