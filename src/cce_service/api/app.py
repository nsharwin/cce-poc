"""FastAPI adapter binding routes to :class:`ScoreService`.

This file is only imported when FastAPI is actually installed (the
production image ships it). It deliberately keeps zero business logic —
every handler just forwards to ``ScoreService`` and translates
``ApiError`` to the right HTTP status.
"""

from __future__ import annotations

import hmac as _hmac
import logging
import os
from typing import Any

_body_limit_logger = logging.getLogger("cce_service.api.body_limit")

try:  # pragma: no cover - optional FastAPI dependency
    from fastapi import FastAPI, Header, HTTPException, Request
    from starlette import status
except Exception:  # pragma: no cover - FastAPI not installed
    FastAPI = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    status = None  # type: ignore[assignment]

from cce_service.api.service import ApiError, ScoreService
from cce_service.logging_setup import setup_json_logging

_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB


async def _send_json(send: Any, status_code: int, payload: dict) -> None:
    """Emit a minimal JSON ASGI response — used by the body-size middleware
    so it can short-circuit before the app sees the request."""
    import json as _json

    body = _json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def build_app(service: ScoreService) -> Any:  # pragma: no cover - prod only
    """Return a configured FastAPI ``app`` bound to ``service``."""
    setup_json_logging()

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

    class _BodySizeLimitMiddleware:
        """Pure-ASGI middleware that bounds request body size.

        Rejects oversized bodies whether the client honestly declares a
        ``Content-Length``, lies about it, or omits it entirely via
        ``Transfer-Encoding: chunked``. Counts bytes off the ASGI receive
        channel so a forged header cannot bypass the limit.
        """

        def __init__(self, asgi_app: Any, max_bytes: int) -> None:
            self.app = asgi_app
            self.max_bytes = max_bytes

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope.get("headers", [])}
            cl = headers.get("content-length")
            if cl is not None:
                try:
                    declared = int(cl)
                except ValueError:
                    await _send_json(
                        send, 400, {"detail": "invalid content-length header"}
                    )
                    return
                if declared > self.max_bytes:
                    await _send_json(
                        send,
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        {
                            "detail": (
                                f"request body exceeds {self.max_bytes} "
                                "byte limit"
                            )
                        },
                    )
                    return

            received = 0
            too_large = False

            async def limited_receive() -> Any:
                nonlocal received, too_large
                message = await receive()
                if message.get("type") == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_bytes:
                        too_large = True
                return message

            response_started = False

            async def guarded_send(message: Any) -> None:
                nonlocal response_started
                if message.get("type") == "http.response.start":
                    response_started = True
                    if too_large:
                        # Swap the inner app's response start for a 413.
                        await _send_json(
                            send,
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            {
                                "detail": (
                                    f"request body exceeds "
                                    f"{self.max_bytes} byte limit"
                                )
                            },
                        )
                        return
                if too_large and message.get("type") == "http.response.body":
                    # Drop the inner body; 413 has already been emitted.
                    return
                await send(message)

            try:
                await self.app(scope, limited_receive, guarded_send)
            except Exception as exc:
                # Only swallow when the request was already over-limit;
                # otherwise re-raise so genuine bugs aren't masked.
                if not too_large:
                    raise
                _body_limit_logger.warning(
                    "body-limit middleware swallowed inner exception: %s",
                    exc,
                    exc_info=True,
                )
                if not response_started:
                    await _send_json(
                        send,
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        {
                            "detail": (
                                f"request body exceeds "
                                f"{self.max_bytes} byte limit"
                            )
                        },
                    )
                    return
            if too_large and not response_started:
                await _send_json(
                    send,
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    {
                        "detail": (
                            f"request body exceeds "
                            f"{self.max_bytes} byte limit"
                        )
                    },
                )

    app.add_middleware(_BodySizeLimitMiddleware, max_bytes=_MAX_BODY_BYTES)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(authorization: str | None = Header(default=None)) -> Any:
        from fastapi import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        # Treat empty/whitespace-only token as unset so an operator who
        # accidentally configures CCE_METRICS_TOKEN="" cannot silently open
        # the endpoint.
        expected = (os.environ.get("CCE_METRICS_TOKEN") or "").strip()
        # Require CCE_ENV to be explicitly "development" for the open bypass.
        # Unset, empty, or any unrecognized value is treated as non-dev so a
        # forgotten Helm/env value cannot expose /metrics in production.
        env = os.environ.get("CCE_ENV", "").strip().lower()
        is_dev = env == "development"
        if not expected:
            if not is_dev:
                raise HTTPException(status_code=503, detail="metrics endpoint not configured")
        else:
            provided = ""
            if authorization and authorization.lower().startswith("bearer "):
                provided = authorization.split(None, 1)[1]
            if not _hmac.compare_digest(provided, expected):
                raise HTTPException(status_code=401, detail="metrics auth required")
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
