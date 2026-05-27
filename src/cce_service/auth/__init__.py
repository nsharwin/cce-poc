"""OAuth2 client-credentials + JWT verification.

The production deployment configures an external IdP (Auth0, Okta, etc.)
via JWKS. For tests/dev we accept HS256 tokens signed with a shared
secret to keep the surface stdlib-only.
"""

from cce_service.auth.jwks import JwksVerifier, issue_rs256_token
from cce_service.auth.jwt import (
    AuthError,
    JwtVerifier,
    Principal,
    issue_hs256_token,
)
from cce_service.auth.rbac import Scope, require_scope

__all__ = [
    "AuthError",
    "JwtVerifier",
    "JwksVerifier",
    "Principal",
    "Scope",
    "issue_hs256_token",
    "issue_rs256_token",
    "require_scope",
]
