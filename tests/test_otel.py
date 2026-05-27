"""OTel-related unit tests.

Spec: preqo1-span-reconciliation, task 2.5.
Validates Requirements 3.1, 3.2, 3.3, 3.4 — `requirements.lock.txt` carries
hash-pinned entries for `opentelemetry-api`, `opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`, and the transitive deps required
to import `ConsoleSpanExporter` and `OTLPSpanExporter` under
`pip install --require-hashes --no-deps`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCKFILE = REPO_ROOT / "requirements.lock.txt"

# Package header: `<name>==X.Y.Z` at start of line, optionally followed by
# a trailing line continuation backslash. The `\b` after the third number
# group keeps the regex anchored to a true X.Y.Z pin and rejects looser
# shapes like `==1.27` or `==1.27.0a1`.
_VERSION_PIN_RE = re.compile(r"^[A-Za-z0-9._-]+==[0-9]+\.[0-9]+\.[0-9]+\b")
_HASH_LINE_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}\b")


def _read_lockfile() -> list[str]:
    return LOCKFILE.read_text(encoding="utf-8").splitlines()


def _extract_package_block(lines: list[str], package: str) -> list[str]:
    """Return the lines belonging to `<package>==X.Y.Z` plus its continuation.

    A package block starts at the line matching `^<package>==X.Y.Z` and
    continues through every following line whose first character is
    whitespace (the indented `--hash=...` continuation lines and the
    `# via` comment trailer that uv emits). The block ends at the first
    line that starts at column zero.

    Returns an empty list if the package is not present.
    """
    header_re = re.compile(
        rf"^{re.escape(package)}==[0-9]+\.[0-9]+\.[0-9]+\b"
    )
    block: list[str] = []
    in_block = False
    for line in lines:
        if not in_block:
            if header_re.match(line):
                block.append(line)
                in_block = True
            continue
        if line.startswith((" ", "\t")):
            block.append(line)
        else:
            break
    return block


def _assert_pinned_with_hashes(package: str) -> None:
    lines = _read_lockfile()
    block = _extract_package_block(lines, package)
    assert block, (
        f"requirements.lock.txt is missing a `{package}==X.Y.Z` entry"
    )
    header = block[0]
    assert _VERSION_PIN_RE.match(header), (
        f"`{package}` is not pinned at an X.Y.Z version: {header!r}"
    )
    hash_lines = [line for line in block[1:] if _HASH_LINE_RE.search(line)]
    assert hash_lines, (
        f"`{package}` has no `--hash=sha256:<64hex>` continuation lines; "
        f"block was:\n{chr(10).join(block)}"
    )


def test_lockfile_pins_opentelemetry_api() -> None:
    """`opentelemetry-api` is pinned to X.Y.Z with at least one sha256 hash."""
    _assert_pinned_with_hashes("opentelemetry-api")


def test_lockfile_pins_opentelemetry_sdk() -> None:
    """`opentelemetry-sdk` is pinned to X.Y.Z with at least one sha256 hash."""
    _assert_pinned_with_hashes("opentelemetry-sdk")


def test_lockfile_pins_opentelemetry_exporter_otlp_proto_http() -> None:
    """`opentelemetry-exporter-otlp-proto-http` is pinned with hashes."""
    _assert_pinned_with_hashes("opentelemetry-exporter-otlp-proto-http")


@pytest.mark.parametrize(
    "package",
    [
        "opentelemetry-proto",
        "opentelemetry-exporter-otlp-proto-common",
        "googleapis-common-protos",
        "protobuf",
        "deprecated",
        "wrapt",
        "importlib-metadata",
    ],
)
def test_lockfile_pins_otel_transitives(package: str) -> None:
    """Each OTel transitive dep is pinned at X.Y.Z with at least one sha256 hash.

    These are the transitives required to import
    `opentelemetry.sdk.trace.export.ConsoleSpanExporter` and
    `opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter`
    under `pip install --require-hashes --no-deps` (design §"Dev lockfile
    additions").
    """
    _assert_pinned_with_hashes(package)


# ---------------------------------------------------------------------------
# init_otel example tests (task 2.6)
# ---------------------------------------------------------------------------
# Validates: Requirements 2.1, 2.2, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9.
#
# These are example-shaped (one assertion per state) counterparts to the
# Hypothesis-flavoured property tests in ``tests/test_otel_properties.py``
# Property 3. The same monkeypatched-spy approach as task 2.2 is used so
# the exporter / processor wiring is hermetic — no daemon threads, no
# global ``TracerProvider`` pollution across tests.

import contextlib
import io
import sys
from typing import Any

import cce.otel as cce_otel


def _reset_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level ``_INITIALISED`` guard so the next
    ``init_otel()`` call behaves as a first-call-in-process."""
    monkeypatch.setattr(cce_otel, "_INITIALISED", False)


def _clear_otlp_endpoint_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear both ``OTLP_Endpoint_Vars`` so the Console_Exporter branch
    is selected by ``init_otel``."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


def _install_spies(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[tuple[type, dict[str, Any]]],
) -> tuple[type, type]:
    """Patch the SDK exporter / processor classes and the global
    ``trace.set_tracer_provider`` with hermetic spies. Returns the
    ``(_SpyConsoleSpanExporter, _SpyOTLPSpanExporter)`` classes so
    callers can assert the recorded class identity."""
    sdk_export = pytest.importorskip("opentelemetry.sdk.trace.export")
    otlp_te = pytest.importorskip(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    )
    trace_module = pytest.importorskip("opentelemetry.trace")

    class _SpyConsoleSpanExporter:
        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyConsoleSpanExporter, dict(kwargs)))

        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyOTLPSpanExporter:
        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyOTLPSpanExporter, dict(kwargs)))

        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyBatchSpanProcessor:
        def __init__(self, exporter: object) -> None:
            self._exporter = exporter

        def on_start(self, _span: object, _parent_context: object = None) -> None:
            return None

        def on_end(self, _span: object) -> None:
            return None

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    monkeypatch.setattr(sdk_export, "ConsoleSpanExporter", _SpyConsoleSpanExporter)
    monkeypatch.setattr(sdk_export, "BatchSpanProcessor", _SpyBatchSpanProcessor)
    monkeypatch.setattr(otlp_te, "OTLPSpanExporter", _SpyOTLPSpanExporter)
    monkeypatch.setattr(trace_module, "set_tracer_provider", lambda _provider: None)

    return _SpyConsoleSpanExporter, _SpyOTLPSpanExporter


# ---------------------------------------------------------------------------
# test_endpoint_detection_* — example-shaped, one assertion per state
# ---------------------------------------------------------------------------
# Validates: Requirements 2.1, 2.2, 2.4, 2.9.
#
# Mirrors the four-state input of Property 3 (``tests/test_otel_properties.py``
# task 2.2). Each state has its own named test so a reviewer can locate
# any failing cell by string-search and the failure message names exactly
# one ``OTLP_Endpoint_Vars`` configuration.


def test_endpoint_detection_both_unset_selects_console_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both endpoint env vars unset → ``ConsoleSpanExporter(out=sys.stderr)``.

    Validates: Requirements 2.2, 2.4, 2.9.
    """
    recorded: list[tuple[type, dict[str, Any]]] = []
    spy_console, spy_otlp = _install_spies(monkeypatch, recorded)

    _clear_otlp_endpoint_env_vars(monkeypatch)
    _reset_initialised(monkeypatch)

    cce_otel.init_otel()

    assert len(recorded) == 1, (
        f"expected exactly one exporter constructor call, got {recorded!r}"
    )
    cls, kwargs = recorded[0]
    assert cls is spy_console, (
        f"both unset: expected ConsoleSpanExporter, got {cls.__name__}"
    )
    # Per design §B "init_otel decision diagram": ``out=sys.stderr``
    # exactly. The ``formatter=`` kwarg is also passed (Requirement 2.3
    # one-line-per-span contract) — we assert its presence without
    # locking the lambda's identity.
    assert kwargs.get("out") is sys.stderr, (
        f"both unset: expected out=sys.stderr, got out={kwargs.get('out')!r}"
    )
    assert "formatter" in kwargs, (
        f"both unset: ConsoleSpanExporter must be constructed with an "
        f"explicit formatter (Requirement 2.3); kwargs={kwargs!r}"
    )


def test_endpoint_detection_only_traces_set_selects_otlp_with_traces_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` set → ``OTLPSpanExporter(endpoint=<traces>)``.

    Validates: Requirements 2.1, 2.9.
    """
    recorded: list[tuple[type, dict[str, Any]]] = []
    spy_console, spy_otlp = _install_spies(monkeypatch, recorded)

    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "http://collector.local:4318/v1/traces",
    )
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset_initialised(monkeypatch)

    cce_otel.init_otel()

    assert len(recorded) == 1, (
        f"expected exactly one exporter constructor call, got {recorded!r}"
    )
    cls, kwargs = recorded[0]
    assert cls is spy_otlp, (
        f"only TRACES set: expected OTLPSpanExporter, got {cls.__name__}"
    )
    assert kwargs == {"endpoint": "http://collector.local:4318/v1/traces"}


def test_endpoint_detection_only_generic_set_selects_otlp_with_generic_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``OTEL_EXPORTER_OTLP_ENDPOINT`` set → ``OTLPSpanExporter(endpoint=<generic>)``.

    Validates: Requirements 2.1, 2.9.
    """
    recorded: list[tuple[type, dict[str, Any]]] = []
    spy_console, spy_otlp = _install_spies(monkeypatch, recorded)

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://generic.local:4318",
    )
    _reset_initialised(monkeypatch)

    cce_otel.init_otel()

    assert len(recorded) == 1, (
        f"expected exactly one exporter constructor call, got {recorded!r}"
    )
    cls, kwargs = recorded[0]
    assert cls is spy_otlp, (
        f"only generic set: expected OTLPSpanExporter, got {cls.__name__}"
    )
    assert kwargs == {"endpoint": "http://generic.local:4318"}


def test_endpoint_detection_both_set_traces_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both endpoint env vars set → TRACES wins per Requirement 2.1.

    Validates: Requirements 2.1, 2.9.
    """
    recorded: list[tuple[type, dict[str, Any]]] = []
    spy_console, spy_otlp = _install_spies(monkeypatch, recorded)

    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "http://traces.local:4318/v1/traces",
    )
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://generic.local:4318",
    )
    _reset_initialised(monkeypatch)

    cce_otel.init_otel()

    assert len(recorded) == 1, (
        f"expected exactly one exporter constructor call, got {recorded!r}"
    )
    cls, kwargs = recorded[0]
    assert cls is spy_otlp, (
        f"both set: expected OTLPSpanExporter, got {cls.__name__}"
    )
    # TRACES wins when both are set.
    assert kwargs == {"endpoint": "http://traces.local:4318/v1/traces"}


# ---------------------------------------------------------------------------
# test_idempotent_init — Requirement 2.5
# ---------------------------------------------------------------------------
# Reset ``_INITIALISED = False`` once, install spy exporters, call
# ``init_otel()`` twice, capture the installed ``TracerProvider``, and
# assert (a) the installed ``TracerProvider`` is the same instance both
# times and (b) the spy constructor count is exactly 1 across the pair
# of calls.


def test_idempotent_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second ``init_otel()`` call leaves the first invocation's exporter
    and ``TracerProvider`` untouched.

    Validates: Requirement 2.5.
    """
    sdk_export = pytest.importorskip("opentelemetry.sdk.trace.export")
    otlp_te = pytest.importorskip(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    )
    trace_module = pytest.importorskip("opentelemetry.trace")

    recorded: list[tuple[type, dict[str, Any]]] = []
    installed_providers: list[object] = []

    class _SpyConsoleSpanExporter:
        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyConsoleSpanExporter, dict(kwargs)))

        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyOTLPSpanExporter:
        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyOTLPSpanExporter, dict(kwargs)))

        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyBatchSpanProcessor:
        def __init__(self, exporter: object) -> None:
            self._exporter = exporter

        def on_start(self, _span: object, _parent_context: object = None) -> None:
            return None

        def on_end(self, _span: object) -> None:
            return None

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    monkeypatch.setattr(sdk_export, "ConsoleSpanExporter", _SpyConsoleSpanExporter)
    monkeypatch.setattr(sdk_export, "BatchSpanProcessor", _SpyBatchSpanProcessor)
    monkeypatch.setattr(otlp_te, "OTLPSpanExporter", _SpyOTLPSpanExporter)

    # Capture each ``set_tracer_provider`` call without polluting the
    # global tracer provider state.
    def _capture_set_tracer_provider(provider: object) -> None:
        installed_providers.append(provider)

    monkeypatch.setattr(
        trace_module, "set_tracer_provider", _capture_set_tracer_provider
    )

    _clear_otlp_endpoint_env_vars(monkeypatch)
    _reset_initialised(monkeypatch)

    # First call — Console_Exporter branch, installs a TracerProvider once.
    cce_otel.init_otel()
    assert len(recorded) == 1, (
        f"first init_otel(): expected exactly one exporter constructor "
        f"call, got {recorded!r}"
    )
    assert len(installed_providers) == 1, (
        f"first init_otel(): expected exactly one set_tracer_provider "
        f"call, got {len(installed_providers)}"
    )
    first_provider = installed_providers[0]

    # Second call — guarded by ``_INITIALISED``; must be a complete no-op.
    cce_otel.init_otel()
    assert len(recorded) == 1, (
        f"second init_otel(): exporter constructor was called again; "
        f"recorded={recorded!r}"
    )
    assert len(installed_providers) == 1, (
        f"second init_otel(): set_tracer_provider was called again; "
        f"installed_providers={installed_providers!r}"
    )
    # Identity check: the same instance is still installed (we did not
    # replace it with a fresh object). Equivalent to the spec text's
    # "installed TracerProvider is the same instance".
    assert installed_providers[0] is first_provider


# ---------------------------------------------------------------------------
# test_noop_tracer_fallback_on_import_error — Requirement 2.6
# ---------------------------------------------------------------------------


class _OpentelemetryBlockingFinder:
    """``meta_path`` finder that raises ``ImportError`` for any
    ``opentelemetry`` or ``opentelemetry.*`` import attempt.

    Used by ``test_noop_tracer_fallback_on_import_error`` to simulate a
    Python environment where the OpenTelemetry SDK packages are not
    installed at all. ``init_otel``'s soft-import block must catch the
    resulting ``ImportError`` and leave ``_NoopTracer`` active.
    """

    @classmethod
    def find_spec(
        cls,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> None:
        if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
            raise ImportError(f"blocked by test: {fullname}")
        return None


def test_noop_tracer_fallback_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK ``ImportError`` leaves ``_NoopTracer`` active and raises nothing.

    Validates: Requirement 2.6.
    """
    # Drop every cached ``opentelemetry*`` module so the soft-import
    # block inside ``init_otel`` re-resolves through ``sys.meta_path``.
    cached_otel = [
        name
        for name in list(sys.modules)
        if name == "opentelemetry" or name.startswith("opentelemetry.")
    ]
    for name in cached_otel:
        monkeypatch.delitem(sys.modules, name, raising=False)

    # Insert the blocking finder at the head of ``sys.meta_path``;
    # ``monkeypatch`` restores the original list on test teardown.
    original_meta_path = list(sys.meta_path)
    monkeypatch.setattr(sys, "meta_path", [_OpentelemetryBlockingFinder, *original_meta_path])

    _clear_otlp_endpoint_env_vars(monkeypatch)
    _reset_initialised(monkeypatch)

    # Property under test: ``init_otel`` swallows ``ImportError``
    # silently, with no log line and no exception propagated.
    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        cce_otel.init_otel()  # must not raise
    assert captured_stderr.getvalue() == "", (
        f"init_otel wrote to stderr on ImportError fallback: "
        f"{captured_stderr.getvalue()!r}"
    )

    # ``get_tracer("cce")`` must fall back to the ``_NoopTracer`` instance
    # because the ``opentelemetry`` package itself is unimportable.
    tracer = cce_otel.get_tracer("cce")
    assert isinstance(tracer, cce_otel._NoopTracer), (
        f"expected _NoopTracer fallback on ImportError, got "
        f"{type(tracer).__name__} ({type(tracer).__module__})"
    )


# ---------------------------------------------------------------------------
# test_noop_tracer_fallback_on_constructor_exception — Requirement 2.7
# ---------------------------------------------------------------------------


def test_noop_tracer_fallback_on_constructor_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ConsoleSpanExporter`` constructor raising ``RuntimeError("boom")``
    leaves a ``_NoopTracer``-shaped fallback active and emits exactly one
    ``init_otel: RuntimeError: boom\\n`` line on ``sys.stderr``.

    Validates: Requirement 2.7.
    """
    sdk_export = pytest.importorskip("opentelemetry.sdk.trace.export")

    class _BoomConsoleSpanExporter:
        def __init__(self, **_kwargs: Any) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        sdk_export, "ConsoleSpanExporter", _BoomConsoleSpanExporter
    )

    _clear_otlp_endpoint_env_vars(monkeypatch)
    _reset_initialised(monkeypatch)

    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        cce_otel.init_otel()  # must not raise

    # Exactly one line of shape ``init_otel: RuntimeError: boom\n``.
    written = captured_stderr.getvalue()
    assert re.fullmatch(r"init_otel: RuntimeError: boom\n", written), (
        f"expected exactly one stderr line matching "
        f"'^init_otel: RuntimeError: boom\\n$', got {written!r}"
    )

    # ``get_tracer("cce")`` falls back to ``_NoopTracer`` per
    # Requirement 2.7 / design §"Constructor exception inside init_otel".
    tracer = cce_otel.get_tracer("cce")
    assert isinstance(tracer, cce_otel._NoopTracer), (
        f"expected _NoopTracer fallback after constructor exception, "
        f"got {type(tracer).__name__} ({type(tracer).__module__})"
    )


# ---------------------------------------------------------------------------
# test_noop_stage_span_writes_no_bytes — Requirement 2.8
# ---------------------------------------------------------------------------


def test_noop_stage_span_writes_no_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``_NoopTracer`` active, ``stage_span`` yields a non-None object
    and writes zero bytes to either ``sys.stdout`` or ``sys.stderr``.

    Validates: Requirement 2.8.
    """
    # Force the ``_NoopTracer`` branch by blocking ``opentelemetry`` imports
    # at the meta_path level (same approach as
    # ``test_noop_tracer_fallback_on_import_error``).
    cached_otel = [
        name
        for name in list(sys.modules)
        if name == "opentelemetry" or name.startswith("opentelemetry.")
    ]
    for name in cached_otel:
        monkeypatch.delitem(sys.modules, name, raising=False)

    original_meta_path = list(sys.meta_path)
    monkeypatch.setattr(
        sys, "meta_path", [_OpentelemetryBlockingFinder, *original_meta_path]
    )

    _clear_otlp_endpoint_env_vars(monkeypatch)
    _reset_initialised(monkeypatch)

    cce_otel.init_otel()
    tracer = cce_otel.get_tracer("cce")
    assert isinstance(tracer, cce_otel._NoopTracer), (
        f"precondition failed: expected _NoopTracer, got "
        f"{type(tracer).__name__}"
    )

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
        captured_stderr
    ), cce_otel.stage_span("load_spec", repo="x") as span:
        # Enter must yield a non-None object (the contract is that
        # callers may set attributes on it, even though the
        # _NoopSpan implementation makes those no-ops).
        assert span is not None, (
            "stage_span context yielded None under _NoopTracer"
        )
        # Sanity exercise of the no-op surface — must also write zero
        # bytes per Requirement 2.8.
        span.set_attribute("synthetic", "value")

    assert captured_stdout.getvalue() == "", (
        f"stage_span wrote to stdout under _NoopTracer: "
        f"{captured_stdout.getvalue()!r}"
    )
    assert captured_stderr.getvalue() == "", (
        f"stage_span wrote to stderr under _NoopTracer: "
        f"{captured_stderr.getvalue()!r}"
    )


# ---------------------------------------------------------------------------
# test_prd_span_names_tuple_identity — locks design §C contract
# ---------------------------------------------------------------------------


def test_prd_span_names_tuple_identity() -> None:
    """``PRD_SPAN_NAMES`` and ``ALLOWED_SPAN_NAMES`` match the design §C
    contract verbatim.

    Validates: Requirements 1.6, 1.7, 1.8 (the bare-name half of the
    span-name closure invariant; the prefixed-form ``cce.<name>`` half
    is enforced by the Span_Gate CI step).
    """
    from cce.otel import ALLOWED_SPAN_NAMES, PRD_SPAN_NAMES

    assert PRD_SPAN_NAMES == ("load_spec", "clone", "parse", "measure", "score")
    assert ALLOWED_SPAN_NAMES == PRD_SPAN_NAMES + ("write_outputs",)


# ---------------------------------------------------------------------------
# test_console_exporter_emits_json_lines_to_stderr — task 2.7
# ---------------------------------------------------------------------------
# Validates: Requirements 2.3, 3.7.
#
# Real-subprocess integration test (NOT a monkeypatched unit test) — it
# verifies the full Console_Exporter wiring from ``init_otel`` through
# ``BatchSpanProcessor`` to stderr emission, end-to-end, in the dev
# image after task 2.4 (lockfile additions) has landed.
#
# The fixture ``tests/fixtures/simple_python`` is a plain source tree
# without a ``.git`` directory; ``cce score --mode repo`` requires a git
# repo at ``--repo``, so we copy the fixture into a tmpdir and ``git
# init`` it deterministically (matching the same env-var pattern used
# by ``tests/test_submodule_trap.py::_git_init_fixture`` and the
# ``Span_Gate`` step in ``.github/workflows/poc-determinism.yml``). If
# ``git`` is not on ``PATH``, the test skips with a clear reason rather
# than failing.

import json
import os
import shutil
import subprocess

_TRACE_ID_RE = re.compile(r"^0x[0-9a-f]{32}$")
_SPAN_NAME_RE = re.compile(r"^cce\.[a-z_]+$")


def _git_init_fixture_for_otel(work: Path) -> str:
    """Run ``git init`` + ``add`` + ``commit`` against ``work`` with the
    deterministic env vars from ``docs/reproductions/README.md``. Returns
    the resulting commit SHA. Mirrors
    ``tests/test_submodule_trap.py::_git_init_fixture`` so this test
    follows the same git-init pattern that other subprocess-based tests
    use.
    """
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CCE Test",
        "GIT_AUTHOR_EMAIL": "cce@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "CCE Test",
        "GIT_COMMITTER_EMAIL": "cce@example.test",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    }
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main"],
        cwd=work,
        check=True,
        env=env,
    )
    subprocess.run(["git", "add", "."], cwd=work, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"],
        cwd=work,
        check=True,
        env=env,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_console_exporter_emits_json_lines_to_stderr(tmp_path: Path) -> None:
    """End-to-end: ``cce score`` with both ``OTLP_Endpoint_Vars`` cleared
    emits at least one JSON-line span to ``sys.stderr`` whose ``name``
    field matches ``^cce\\.[a-z_]+$`` and whose ``context.trace_id``
    field is a string of shape ``0x[0-9a-f]{32}``.

    Verifies the full Console_Exporter wiring from ``init_otel`` through
    ``BatchSpanProcessor`` to ``sys.stderr`` emission, end-to-end. This
    is the only smoke test in the suite that exercises the real SDK
    pipeline (no monkeypatched spies).

    Validates: Requirements 2.3, 3.7.
    """
    # Hard import — Requirement 3.7 / task 2.7 explicitly assumes the
    # OpenTelemetry SDK is installed (i.e. inside the dev image after
    # task 2.4 landed). If the SDK is absent for any reason the
    # subprocess would silently fall back to ``_NoopTracer`` and emit
    # zero JSON lines, which is the wrong failure mode for this test.
    pytest.importorskip("opentelemetry.sdk.trace.export")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    if shutil.which("git") is None:
        pytest.skip("git is not on PATH; cannot init the simple_python fixture")

    fixture_src = REPO_ROOT / "tests" / "fixtures" / "simple_python"
    work = tmp_path / "simple_python"
    shutil.copytree(fixture_src, work)
    try:
        _git_init_fixture_for_otel(work)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"git init failed in test env: {exc}")

    spec = REPO_ROOT / "scoring-spec.yaml"
    out = tmp_path / "cce-out"
    out.mkdir()

    # Both ``OTLP_Endpoint_Vars`` MUST be cleared so ``init_otel``
    # selects the Console_Exporter branch (Requirements 2.2, 2.3). We
    # propagate the rest of the parent environment so ``uv run`` and the
    # editable install can resolve.
    env = {**os.environ}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    env.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
    # ``PYTHONPATH`` lets ``python -m cce`` resolve the package without
    # depending on ``uv run`` being on PATH inside the test environment.
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "cce",
            "score",
            "--spec",
            str(spec),
            "--repo",
            str(work),
            "--mode",
            "repo",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    # Sanity precondition: the run must have succeeded, otherwise the
    # JSON-line assertion is meaningless. If this fails, the failure
    # message includes both streams so the operator can triage.
    assert proc.returncode == 0, (
        f"cce score exited with {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )

    # Parse stderr line-by-line. Per task 2.7: split on ``\n``; for each
    # line attempt ``json.loads``; collect parsed dict objects whose
    # ``name`` is a str matching ``^cce\.[a-z_]+$`` AND whose
    # ``context.trace_id`` is a str of shape ``0x[0-9a-f]{32}`` (the
    # ``0x`` prefix is stripped before measuring length per design
    # §"Span JSON-line schema").
    matching: list[dict[str, Any]] = []
    for line in proc.stderr.split("\n"):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str) or not _SPAN_NAME_RE.match(name):
            continue
        context = obj.get("context")
        if not isinstance(context, dict):
            continue
        trace_id = context.get("trace_id")
        if not isinstance(trace_id, str) or not _TRACE_ID_RE.match(trace_id):
            continue
        matching.append(obj)

    assert matching, (
        "expected at least one stderr line to be a single JSON object "
        "with a 'name' field matching '^cce\\.[a-z_]+$' AND a "
        "'context.trace_id' field of shape '0x[0-9a-f]{32}', but found "
        f"none. Captured stderr was:\n{proc.stderr!r}"
    )
