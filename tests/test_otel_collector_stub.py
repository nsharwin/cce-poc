# Feature: preqo1-span-reconciliation, in-process stub OTLP collector helper for Property 1 / 2 / 5 OTLP-branch tests  # noqa: E501
"""In-process stub OTLP/HTTP collector for OTLP-branch property tests.

This module is a **helper, not a test file**. The filename matches the
``test_*.py`` glob because pytest's ``testpaths`` is ``tests/`` and the
spec (task 3.4) explicitly names this file. The module deliberately
defines no ``test_*`` functions and no ``Test*`` classes, so pytest
collects zero items from it during a normal run.

Provides:

- :class:`StubOtlpCollector` — wraps ``http.server.ThreadingHTTPServer``
  with a ``BaseHTTPRequestHandler`` that listens on ``127.0.0.1:0``
  (kernel-assigned port) and records POST request bodies into a list.
  Exposes ``endpoint_url`` returning ``http://127.0.0.1:<port>/v1/traces``.
- :func:`start_collector` — context manager that spawns the HTTP server
  on a daemon thread, yields the :class:`StubOtlpCollector` instance,
  and tears the server down on exit.
- :func:`extract_span_names` — parses the recorded OTLP-protobuf
  payloads using the ``opentelemetry-proto`` types and returns the set
  of span names. The protobuf import is lazy so this module remains
  importable even before task 2.4 lands the lockfile additions; callers
  that invoke :func:`extract_span_names` will surface :class:`ImportError`
  at call time if the proto package is not yet installed.

Used by tasks 3.2, 3.3 (and any later Property 1 OTLP-branch extension).

Network-isolation note: the collector binds to ``127.0.0.1`` only and
makes no outbound connections, so it is compatible with the
``--network=none`` CI invariant established by `POC-GATE-5`.
"""
from __future__ import annotations

import contextlib
import gzip
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ["StubOtlpCollector", "start_collector", "extract_span_names"]


class StubOtlpCollector:
    """In-process stub OTLP/HTTP receiver.

    Records the (decompressed) request body of every ``POST`` request it
    receives into :attr:`payloads`. Each entry is the protobuf-serialised
    ``ExportTraceServiceRequest`` bytes — gzip-encoded payloads (the OTLP
    HTTP exporter's default) are decompressed on receipt so callers do
    not need to care about transport encoding.

    Construct via :func:`start_collector`; do not instantiate directly.
    """

    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint_url(self) -> str:
        """OTLP/HTTP traces endpoint URL of the running collector."""
        if self._server is None:
            raise RuntimeError("StubOtlpCollector is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1/traces"

    def _start(self) -> None:
        collector = self  # captured by the handler closure

        class _Handler(BaseHTTPRequestHandler):
            # Suppress default request logging to stderr (would pollute
            # stdout-discipline assertions in Property 5).
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length > 0 else b""
                encoding = (self.headers.get("Content-Encoding") or "").lower().strip()
                if encoding == "gzip" and raw:
                    try:
                        body = gzip.decompress(raw)
                    except OSError:
                        # Not actually gzipped; record as-is.
                        body = raw
                else:
                    body = raw
                collector.payloads.append(body)
                # Respond with an empty ExportTraceServiceResponse (no
                # partial_success). An empty protobuf message serialises
                # to zero bytes, which the OTLP HTTP exporter accepts.
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="StubOtlpCollector",
            daemon=True,
        )
        self._thread.start()

    def _stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None


@contextlib.contextmanager
def start_collector() -> Iterator[StubOtlpCollector]:
    """Spawn a :class:`StubOtlpCollector` on a daemon thread.

    Yields the collector instance with its HTTP server already accepting
    connections; tears the server down on context exit.

    Example::

        with start_collector() as collector:
            os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = collector.endpoint_url
            # ... run cce score ...
        names = extract_span_names(collector.payloads)
    """
    collector = StubOtlpCollector()
    collector._start()
    try:
        yield collector
    finally:
        collector._stop()


def extract_span_names(payloads: list[bytes]) -> set[str]:
    """Return the set of span names found in OTLP-protobuf payloads.

    Each element of ``payloads`` is an ``ExportTraceServiceRequest``
    protobuf message body (already decompressed by
    :class:`StubOtlpCollector`). Empty payloads are skipped. Span ``name``
    fields that are empty strings are also skipped — the OTel SDK never
    emits empty span names but the wire format permits them.

    The ``opentelemetry-proto`` import is performed lazily so this module
    can be imported in environments where task 2.4's lockfile additions
    have not yet landed.
    """
    # Lazy import: opentelemetry-proto is added by task 2.4. Importing
    # at module load time would make this file un-importable on any
    # branch where the lockfile bump has not yet merged.
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    names: set[str] = set()
    for body in payloads:
        if not body:
            continue
        request = ExportTraceServiceRequest()
        request.ParseFromString(body)
        for resource_spans in request.resource_spans:
            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    if span.name:
                        names.add(span.name)
    return names
