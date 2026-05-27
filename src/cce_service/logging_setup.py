"""Structured JSON logging setup for the CCE service.

Gated behind ``CCE_LOG_FORMAT=json`` env var. When unset (default),
logging emits plain-text to stderr — no dependency on any JSON library.

With ``CCE_LOG_FORMAT=json``, all log records are serialised as one JSON
object per line, including: timestamp, level, logger name, message,
correlation fields (request_id, trace_id, span_id, job_id) when available.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cce_request_id", default=None
)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cce_trace_id", default=None
)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cce_span_id", default=None
)


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        req_id = _request_id.get()
        if req_id:
            payload["request_id"] = req_id
        trace = _trace_id.get()
        if trace:
            payload["trace_id"] = trace
        span = _span_id.get()
        if span:
            payload["span_id"] = span
        job_id = getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = job_id
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = repr(record.exc_info[1])
        return json.dumps(payload, separators=(",", ":"))


def setup_json_logging() -> None:
    if os.environ.get("CCE_LOG_FORMAT") != "json":
        return
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLineFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def set_job_id(record: logging.LogRecord, job_id: str) -> None:
    record.job_id = job_id


class JobLogAdapter(logging.LoggerAdapter):
    def process(self, msg: object, kwargs: dict) -> tuple:
        extra = kwargs.get("extra", {})
        if self.extra:
            extra.update(self.extra)
            kwargs["extra"] = extra
        return msg, kwargs


__all__ = [
    "JobLogAdapter",
    "JsonLineFormatter",
    "set_job_id",
    "set_request_id",
    "setup_json_logging",
]
