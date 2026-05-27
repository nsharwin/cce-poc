"""API surface for the CCE production service.

``service.py`` contains the transport-agnostic handlers (testable without
FastAPI installed). ``app.py`` is the FastAPI wiring that calls into
``service.py``; it imports lazily so the POC dev env doesn't need
FastAPI.
"""

from cce_service.api.service import (
    ApiError,
    Forbidden,
    ScoreJobView,
    ScoreRecordView,
    ScoreService,
    Unauthorized,
)

__all__ = [
    "ApiError",
    "Forbidden",
    "ScoreJobView",
    "ScoreRecordView",
    "ScoreService",
    "Unauthorized",
]
