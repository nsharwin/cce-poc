"""Shared pytest fixtures for the cce-poc test suite."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _default_cce_env_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default ``CCE_ENV=development`` for all tests.

    Several constructors (``JwtVerifier``, ``JwksVerifier``) hard-fail outside
    development. Individual tests that need to exercise production behavior
    explicitly call ``monkeypatch.setenv("CCE_ENV", "production")`` or
    ``monkeypatch.delenv("CCE_ENV", raising=False)`` to override this default.

    Uses setdefault semantics: if the operator has already exported ``CCE_ENV``
    in their shell (e.g. ``CCE_ENV=production pytest …`` to reproduce a bug),
    that value wins. This keeps CI deterministic while letting local runs
    reflect the operator's intended environment.
    """
    if "CCE_ENV" not in os.environ:
        monkeypatch.setenv("CCE_ENV", "development")
