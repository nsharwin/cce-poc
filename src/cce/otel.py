"""OpenTelemetry + Prometheus instrumentation for CCE (PREQ-O-1).

Design goals:

- **Zero impact on determinism**: instrumentation must never change
  ``record_hash`` or scoring output. All side-effects (span exports,
  counter increments) are emitted *around* the deterministic core.
- **Soft import**: the POC dev image is not required to ship the OTel SDK.
  When the SDK is unavailable, :func:`get_tracer` returns a no-op tracer
  and the metric helpers become silent counters; the production image
  installs ``opentelemetry-sdk`` + ``opentelemetry-exporter-otlp`` +
  ``prometheus-client`` (added in ``requirements.lock.txt``) and a real
  pipeline is configured via env vars.
- **Configured by env**: ``OTEL_EXPORTER_OTLP_ENDPOINT`` selects the
  collector; ``OTEL_SERVICE_NAME`` defaults to ``cce``; resource attrs
  ``service.version`` are picked up from ``cce.__version__``.

Public surface used by the CLI and the future ``cce_service``:

- :func:`init_otel` — idempotent one-time setup; safe to call at every
  process start.
- :func:`get_tracer` — returns a ``Tracer`` (no-op when SDK is absent).
- :func:`stage_span` — context manager: ``with stage_span("analyze",
  record_hash=...) as span: ...``.
- :data:`SCORE_DURATION_SECONDS`, :data:`RECORDS_TOTAL`,
  :data:`JOB_FAILURES_TOTAL` — Prometheus instruments (no-op fallbacks
  when ``prometheus_client`` is absent).

PREQ-O-1 span name contract:

- :data:`PRD_SPAN_NAMES` is the tuple of bare stage names declared by
  ``PREQ-O-1`` in ``docs/poc-prd.md``:
  ``("load_spec", "clone", "parse", "measure", "score")``. The full
  ``PRD_Span_Set`` referenced throughout the spec design is
  ``{f"cce.{name}" for name in PRD_SPAN_NAMES}``, i.e.
  ``{"cce.load_spec", "cce.clone", "cce.parse", "cce.measure", "cce.score"}``.
- :data:`ALLOWED_SPAN_NAMES` extends :data:`PRD_SPAN_NAMES` with
  ``"write_outputs"``. The span ``cce.write_outputs`` is the only
  emitted span name outside ``PRD_Span_Set``; every other span emitted
  via :func:`stage_span` MUST resolve to a member of ``PRD_Span_Set``.
  The set of emitted span names for any single ``cce score`` invocation
  MUST be a subset of
  ``{f"cce.{name}" for name in ALLOWED_SPAN_NAMES}``.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import Any

_INITIALISED = False

# ``True`` whenever ``init_otel`` returned via one of its two fallback paths
# (SDK ImportError or exporter/processor constructor exception). Read by
# :func:`get_tracer` so the active tracer surface is the in-process
# :class:`_NoopTracer` fallback rather than the SDK's :class:`ProxyTracer`,
# matching the design §"Init_otel decision diagram" contract: any path
# leaving init_otel without successfully calling
# ``trace.set_tracer_provider(...)`` MUST leave :class:`_NoopTracer`
# observable to callers (Requirements 2.6, 2.7). This flag is reset to
# ``False`` at the top of every first ``init_otel()`` invocation, so a
# successful invocation in a fresh process unsets any stale fallback
# state from a prior failed reset (e.g. in tests that toggle
# ``_INITIALISED`` between cases).
_FORCE_NOOP = False


# ---------------------------------------------------------------------------
# PREQ-O-1 span name contract (see module docstring for full discussion)
# ---------------------------------------------------------------------------

#: Bare stage names declared by ``PREQ-O-1`` in ``docs/poc-prd.md``. The full
#: ``PRD_Span_Set`` is ``{f"cce.{name}" for name in PRD_SPAN_NAMES}``.
PRD_SPAN_NAMES: tuple[str, ...] = (
    "load_spec",
    "clone",
    "parse",
    "measure",
    "score",
)

#: Bare stage names permitted to be emitted by ``cce score``. Equals
#: :data:`PRD_SPAN_NAMES` plus ``"write_outputs"`` — ``cce.write_outputs`` is
#: the only emitted span outside ``PRD_Span_Set``.
ALLOWED_SPAN_NAMES: tuple[str, ...] = PRD_SPAN_NAMES + ("write_outputs",)


# ---------------------------------------------------------------------------
# Soft tracing surface
# ---------------------------------------------------------------------------


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _NoopTracer:
    @contextlib.contextmanager
    def start_as_current_span(self, name: str, **_kwargs: Any) -> Iterator[_NoopSpan]:
        yield _NoopSpan()


def _stripped_env(name: str) -> str | None:
    """Return ``os.environ[name]`` with leading/trailing ASCII whitespace
    stripped, or ``None`` if the variable is missing or empty after stripping.

    Used by :func:`init_otel` to enforce the ``OTLP_Endpoint_Vars`` "set"
    predicate from the requirements glossary: an env var counts as "set"
    only when it is present AND non-empty after whitespace stripping.

    Module-private; not part of :data:`__all__`.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def init_otel(service_name: str = "cce", service_version: str = "0.1.0") -> None:
    """Configure the OTel SDK once per process. Idempotent.

    Selection rule (Requirement 2.1, 2.2):
      1. If ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` is set after stripping
         whitespace, install an :class:`OTLPSpanExporter` against that
         endpoint via a :class:`BatchSpanProcessor`.
      2. Else if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set after stripping
         whitespace, install an :class:`OTLPSpanExporter` against that
         endpoint via a :class:`BatchSpanProcessor`.
      3. Else install a :class:`ConsoleSpanExporter` writing JSON-line
         spans to ``sys.stderr`` via a :class:`BatchSpanProcessor`.

    The endpoint is passed to ``OTLPSpanExporter(endpoint=...)``
    explicitly (rather than relying on the SDK's own env-var precedence)
    so the precedence rule "TRACES wins when both are set" is enforced
    by this code, not by the SDK — defensive against future SDK behavior
    changes.

    Failure modes (no exception ever propagates out of this function):

    - If the OpenTelemetry SDK packages cannot be imported, the active
      tracer remains :class:`_NoopTracer` and this function returns
      silently (Requirement 2.6).
    - If any exception is raised during exporter / processor / provider
      construction, this function writes exactly one line to
      ``sys.stderr`` of shape ``init_otel: <ExcClass>: <message>\\n`` and
      returns, leaving :class:`_NoopTracer` active (Requirement 2.7).

    Idempotence: a module-level ``_INITIALISED`` guard ensures that only
    the first invocation per process runs the body; subsequent calls
    return immediately (Requirement 2.5). The guard is set BEFORE the
    SDK import block, so a first failed invocation also locks out
    subsequent attempts within the same process.
    """
    global _INITIALISED, _FORCE_NOOP
    if _INITIALISED:
        return
    _INITIALISED = True
    # Reset the fallback flag so a successful invocation in this process
    # does not inherit stale state from a prior failed
    # ``_INITIALISED = False`` toggle (e.g. between test cases). Any of
    # the two fallback paths below will set this back to ``True`` before
    # returning.
    _FORCE_NOOP = False

    try:  # pragma: no cover - exercised only when SDK is installed
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        _FORCE_NOOP = True
        return  # Requirement 2.6: leave _NoopTracer active, no log, no raise

    try:
        resource = Resource.create(
            {
                "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
                "service.version": service_version,
            }
        )
        provider = TracerProvider(resource=resource)

        traces_endpoint = _stripped_env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        generic_endpoint = _stripped_env("OTEL_EXPORTER_OTLP_ENDPOINT")
        if traces_endpoint is not None:
            exporter: Any = OTLPSpanExporter(endpoint=traces_endpoint)
        elif generic_endpoint is not None:
            exporter = OTLPSpanExporter(endpoint=generic_endpoint)
        else:
            # Requirement 2.3: each exported span MUST be a single JSON
            # object terminated by exactly one ``\n``. The SDK's default
            # ``ConsoleSpanExporter`` formatter calls ``span.to_json()``
            # which defaults to ``indent=4`` (pretty-printed multi-line
            # output) — that violates the one-line-per-span contract the
            # design §B.7 parser depends on. Pass an explicit formatter
            # that pins ``indent=None`` so the output is one compact JSON
            # object plus a single ``\n`` per span, regardless of the
            # SDK's default.
            exporter = ConsoleSpanExporter(
                out=sys.stderr,
                formatter=lambda span: span.to_json(indent=None) + "\n",
            )

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception as exc:  # noqa: BLE001 - Requirement 2.7
        # Single-line stderr log; leave _NoopTracer active. This is the
        # only place this spec uses bare ``except Exception`` — a
        # deliberate tradeoff to satisfy the "no propagation" contract.
        sys.stderr.write(f"init_otel: {exc.__class__.__name__}: {exc}\n")
        _FORCE_NOOP = True
        return


def get_tracer(name: str = "cce") -> Any:
    """Return the active tracer or a no-op fallback.

    Returns :class:`_NoopTracer` when either:

    * the OpenTelemetry API package cannot be imported, OR
    * :func:`init_otel` returned via one of its two fallback paths
      (SDK ImportError or exporter/processor constructor exception),
      as recorded by the module-level ``_FORCE_NOOP`` flag.

    Otherwise returns ``opentelemetry.trace.get_tracer(name)``.
    """
    if _FORCE_NOOP:
        return _NoopTracer()
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
    except ImportError:
        return _NoopTracer()
    return trace.get_tracer(name)


@contextlib.contextmanager
def stage_span(stage: str, **attrs: Any) -> Iterator[Any]:
    """Context manager that opens an OTel span for a CCE pipeline stage.

    Stage names: ``prepared_repo``, ``analyze``, ``score``, ``write_outputs``.
    """
    tracer = get_tracer("cce")
    with tracer.start_as_current_span(f"cce.{stage}") as span:
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, str(value))
        yield span


# ---------------------------------------------------------------------------
# Soft Prometheus surface
# ---------------------------------------------------------------------------


class _NoopMetric:
    def labels(self, *_args: Any, **_kwargs: Any) -> _NoopMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def dec(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _build_metrics() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:  # pragma: no cover - production only
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:
        return (
            _NoopMetric(),
            _NoopMetric(),
            _NoopMetric(),
            _NoopMetric(),
            _NoopMetric(),
            _NoopMetric(),
            _NoopMetric(),
        )

    duration = Histogram(
        "cce_score_duration_seconds",
        "Wall-clock duration of `cce score` end-to-end, in seconds.",
        labelnames=("stage",),
        buckets=(0.5, 1, 2, 5, 10, 20, 45, 90, 180),
    )
    records = Counter(
        "cce_records_total",
        "Number of successfully scored records.",
    )
    failures = Counter(
        "cce_job_failures_total",
        "Number of scoring jobs that failed, by reason.",
        labelnames=("reason",),
    )
    mismatches = Counter(
        "cce_record_hash_mismatch_total",
        "Number of record_hash mismatches detected.",
        labelnames=("spec_hash", "commit_sha"),
    )
    fc_boot_failures = Counter(
        "cce_firecracker_boot_failures_total",
        "Number of Firecracker microVM boot failures, by reason.",
        labelnames=("reason",),
    )
    queue_depth = Gauge(
        "cce_queue_depth",
        "Current number of jobs in the scoring queue.",
    )
    cb_state = Gauge(
        "cce_circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=half_open, 2=open).",
        labelnames=("name",),
    )
    return duration, records, failures, mismatches, fc_boot_failures, queue_depth, cb_state


(
    SCORE_DURATION_SECONDS,
    RECORDS_TOTAL,
    JOB_FAILURES_TOTAL,
    RECORD_HASH_MISMATCH_TOTAL,
    FIRECRACKER_BOOT_FAILURES_TOTAL,
    QUEUE_DEPTH,
    CIRCUIT_BREAKER_STATE,
) = _build_metrics()


__all__ = [
    "ALLOWED_SPAN_NAMES",
    "CIRCUIT_BREAKER_STATE",
    "FIRECRACKER_BOOT_FAILURES_TOTAL",
    "JOB_FAILURES_TOTAL",
    "PRD_SPAN_NAMES",
    "QUEUE_DEPTH",
    "RECORDS_TOTAL",
    "RECORD_HASH_MISMATCH_TOTAL",
    "SCORE_DURATION_SECONDS",
    "get_tracer",
    "init_otel",
    "stage_span",
]
