"""JWKS-based JWT verifier for production (RS256/ES256).

Production deployments configure ``CCE_JWKS_URI`` to point at an
external IdP (Auth0, Okta, etc.). The verifier fetches the public keys
on first use, caches them by TTL, and validates RS256/ES256 signatures.

The ``cryptography`` library (or ``PyJWT[crypto]``) is **required** for
RS256/ES256 signature verification. If it is not installed, the
verifier refuses to construct outside of ``CCE_ENV=development`` and
all calls to ``_verify_rs256`` / ``_verify_es256`` raise
:class:`AuthError`. There is no silent hash-only fallback: forged
tokens cannot pass through an unverified signature path. The
``_warn_missing_crypto()`` guard enforces this default-deny posture.

The public surface (:class:`Principal`, ``verify(token) -> Principal``)
is identical to :class:`cce_service.auth.jwt.JwtVerifier`, so the
service layer can swap verifiers at configuration time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.request
from collections.abc import Iterable

from cce_service.auth.jwt import AuthError, Principal

_logger = logging.getLogger("cce_service.auth.jwks")

# ---------------------------------------------------------------------------
# Crypto availability detection
# ---------------------------------------------------------------------------

_HAS_CRYPTO = False
try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    _HAS_CRYPTO = True
except ImportError:
    pass


def _warn_missing_crypto() -> None:
    if _HAS_CRYPTO:
        return
    env = os.environ.get("CCE_ENV", "development")
    _logger.critical(
        "cryptography library not installed — JWKS signature verification "
        "is unavailable. Install 'cryptography' or 'PyJWT[crypto]'.",
    )
    if env != "development" and os.environ.get("CCE_ALLOW_HASH_ONLY_JWKS") != "1":
        raise RuntimeError(
            f"JwksVerifier refused to start in env={env!r} without the "
            "cryptography library. Install it or set CCE_ENV=development."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _jwk_thumbprint(jwk: dict[str, object]) -> str:
    """RFC 7638 JWK Thumbprint — deterministic hash of the key's public
    parameters, used for ``kid`` matching."""
    members: dict[str, object]
    kty = jwk.get("kty")
    if kty == "RSA":
        members = {"e": jwk["e"], "kty": jwk["kty"], "n": jwk["n"]}
    elif kty == "EC":
        members = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]}
    else:
        raise AuthError(f"unsupported JWK kty: {kty!r}")
    canonical = json.dumps(members, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


class _JwksCache:
    """Fetches JWKS from a URI and caches it for ``ttl_seconds``."""

    def __init__(self, jwks_uri: str, ttl_seconds: int = 300) -> None:
        self._uri = jwks_uri
        self._ttl = ttl_seconds
        self._fetched_at: float = 0.0
        self._keys: dict[str, dict[str, object]] = {}

    def get(self, kid: str) -> dict[str, object] | None:
        self._maybe_refresh()
        return self._keys.get(kid)

    def _maybe_refresh(self) -> None:
        now = time.monotonic()
        if now - self._fetched_at < self._ttl:
            return
        _logger.info("jwks.fetch uri=%s", self._uri)
        with urllib.request.urlopen(self._uri, timeout=10) as resp:
            body = json.load(resp)
        jwks: list[dict[str, object]] = body.get("keys", [])
        new_keys: dict[str, dict[str, object]] = {}
        for jwk in jwks:
            kid_val = jwk.get("kid")
            if isinstance(kid_val, str):
                new_keys[kid_val] = jwk
            else:
                # Fall back to thumbprint-based lookup when kid is absent.
                new_keys[_jwk_thumbprint(jwk)] = jwk
        self._keys = new_keys
        self._fetched_at = now
        _logger.info("jwks.cached count=%d", len(self._keys))


# ---------------------------------------------------------------------------
# Signature verification (cryptography-backed)
# ---------------------------------------------------------------------------


def _verify_rs256(signing_input: bytes, signature: bytes, jwk: dict[str, object]) -> None:
    if not _HAS_CRYPTO:
        raise AuthError("signature verification unavailable: cryptography not installed")
    e_bytes = _b64url_decode(str(jwk["e"]))
    n_bytes = _b64url_decode(str(jwk["n"]))
    e_int = int.from_bytes(e_bytes, "big")
    n_int = int.from_bytes(n_bytes, "big")
    public_key = rsa.RSAPublicNumbers(e_int, n_int).public_key(default_backend())
    try:
        public_key.verify(
            signature,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise AuthError("bad signature") from exc


def _verify_es256(signing_input: bytes, signature: bytes, jwk: dict[str, object]) -> None:
    if not _HAS_CRYPTO:
        raise AuthError("signature verification unavailable: cryptography not installed")
    x_bytes = _b64url_decode(str(jwk["x"]))
    y_bytes = _b64url_decode(str(jwk["y"]))
    x_int = int.from_bytes(x_bytes, "big")
    y_int = int.from_bytes(y_bytes, "big")
    public_key = ec.EllipticCurvePublicNumbers(
        x_int, y_int, ec.SECP256R1()
    ).public_key(default_backend())
    try:
        public_key.verify(
            signature,
            signing_input,
            ec.ECDSA(hashes.SHA256()),
        )
    except Exception as exc:
        raise AuthError("bad signature") from exc


# ---------------------------------------------------------------------------
# Public verifier
# ---------------------------------------------------------------------------


class JwksVerifier:
    """Validates RS256/ES256 JWTs against a JWKS endpoint.

    Swap-in replacement for :class:`cce_service.auth.jwt.JwtVerifier` —
    same ``verify(token) -> Principal`` contract.
    """

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
        cache_ttl: int = 300,
        leeway_seconds: int = 0,
    ) -> None:
        if not jwks_uri.startswith("https://"):
            raise ValueError("jwks_uri must start with https://")
        _warn_missing_crypto()
        self._cache = _JwksCache(jwks_uri, ttl_seconds=cache_ttl)
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

        alg = header.get("alg")
        if alg not in {"RS256", "ES256"}:
            raise AuthError(f"unsupported alg: {alg!r}")

        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AuthError("missing kid in token header")

        jwk = self._cache.get(kid)
        if jwk is None:
            raise AuthError(f"unknown kid: {kid!r}")

        signing_input = f"{header_b}.{payload_b}".encode()

        if alg == "RS256":
            _verify_rs256(signing_input, signature, jwk)
        elif alg == "ES256":
            _verify_es256(signing_input, signature, jwk)

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


def issue_rs256_token(
    *,
    private_key_pem: str,
    subject: str,
    tenant: str,
    scopes: Iterable[str],
    issuer: str = "cce-prod",
    audience: str = "cce-api",
    ttl_seconds: int = 300,
    key_id: str = "cce-signing-key",
    now: int | None = None,
) -> str:
    """Mint a signed RS256 JWT. Used by tests and integration fixtures."""
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography library is required for RS256 token issuance")
    now_s = int(time.time()) if now is None else now
    header = {"alg": "RS256", "typ": "JWT", "kid": key_id}
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

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None, backend=default_backend()
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b}.{payload_b}.{_b64url_encode(signature)}"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


__all__ = ["JwksVerifier", "issue_rs256_token"]
