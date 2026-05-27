"""Scope-based access control for CCE service endpoints."""

from __future__ import annotations

import enum

from cce_service.auth.jwt import AuthError, Principal


class Scope(enum.StrEnum):
    SCORE_WRITE = "score:write"
    RECORDS_READ = "records:read"
    AUDIT_READ = "audit:read"


def require_scope(principal: Principal, scope: Scope) -> None:
    """Raise :class:`AuthError` (→ HTTP 403) when the scope is missing."""
    if scope.value not in principal.scopes:
        raise AuthError(f"missing required scope: {scope.value}")


__all__ = ["Scope", "require_scope"]
