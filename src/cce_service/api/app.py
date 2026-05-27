"""FastAPI adapter binding routes to :class:`ScoreService`.

This file is only imported when FastAPI is actually installed (the
production image ships it). It deliberately keeps zero business logic —
every handler just forwards to ``ScoreService`` and translates
``ApiError`` to the right HTTP status.
"""

from __future__ import annotations

from typing import Any

from cce_service.api.service import ApiError, ScoreService
from cce_service.logging_setup import setup_json_logging

_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB


def build_app(service: ScoreService) -> Any:  # pragma: no cover - prod only
    """Return a configured FastAPI ``app`` bound to ``service``."""
    setup_json_logging()

    from fastapi import FastAPI, Header, HTTPException, Request
    from starlette import status

    from cce_service.logging_setup import set_request_id

    app = FastAPI(title="CCE Service", version="0.1.0")

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next: Any) -> Any:
        req_id = request.headers.get("X-Request-Id", f"cce-{id(request):x}")
        set_request_id(req_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> Any:
        # Re-raise as HTTPException so FastAPI emits the proper response shape.
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.middleware("http")
    async def _body_size_limit(request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="invalid content-length header"
                ) from None
            if length > _MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"request body exceeds {_MAX_BODY_BYTES} byte limit",
                )
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Any:
        from fastapi import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/scores")
    async def create_score(
        request: Request, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        body = await request.json()
        view = service.create_score(authz_header=authorization, body=body)
        return view.to_json()

    @app.get("/v1/scores/{job_id}")
    async def get_score(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return service.get_score(authz_header=authorization, job_id=job_id).to_json()

    @app.get("/v1/records/{record_hash}")
    async def get_record(
        record_hash: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        view = service.get_record(authz_header=authorization, record_hash=record_hash)
        return {
            "record_hash": view.record_hash,
            "commit_sha": view.commit_sha,
            "repo_url": view.repo_url,
            "spec_hash": view.spec_hash,
            "score": view.score,
            "metrics": view.metrics,
            "tool_digests": view.tool_digests,
        }

    @app.get("/v1/audit")
    async def list_audit(
        since: str, authorization: str | None = Header(default=None)
    ) -> list[dict[str, Any]]:
        return service.list_audit(authz_header=authorization, since_iso=since)

    return app


__all__ = ["build_app"]
