"""Span name set unit tests.

Spec: ``preqo1-span-reconciliation``, task 1.7.
Validates Requirements 1.6, 1.7, 1.8, 1.10, 1.11.

Runs ``cce score`` against ``tests/fixtures/simple_python`` via subprocess
once, captures stderr, parses each newline-delimited line as a JSON span
record per the design §B.7 parser, and asserts:

  * ``test_emitted_span_set_equals_allowed_span_set`` — the set of
    ``cce.*`` span names emitted by ``cce score`` equals
    ``Allowed_Span_Set = {cce.load_spec, cce.clone, cce.parse, cce.measure,
    cce.score, cce.write_outputs}`` (Requirements 1.6, 1.7, 1.8).
  * ``test_no_cce_prepared_repo_span`` — the legacy ``cce.prepared_repo``
    span name is NOT emitted (Requirement 1.10).
  * ``test_no_cce_analyze_span`` — the legacy ``cce.analyze`` span name
    is NOT emitted (Requirement 1.11).
  * ``test_static_source_has_no_legacy_stage_names`` — defense-in-depth
    static check that ``src/cce/cli.py`` does not contain a
    ``stage_span("prepared_repo", ...)`` or ``stage_span("analyze", ...)``
    call (design §F "tests/test_span_names.py").

The first three tests share a single subprocess invocation via a
module-scoped ``pytest`` fixture. The fixture copies ``simple_python``
into a tmpdir, git-init's it deterministically (matching the env-var
contract used by ``.github/workflows/poc-determinism.yml`` and the
existing ``tests/test_submodule_trap.py``), runs ``cce score`` with
both ``OTEL_EXPORTER_OTLP_*`` env vars cleared so the
``ConsoleSpanExporter`` branch is exercised, then parses the captured
stderr with the same line-by-line rules as the Span_Gate parser.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SIMPLE_PYTHON_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "simple_python"
SCORING_SPEC = REPO_ROOT / "scoring-spec.yaml"
CLI_SOURCE = REPO_ROOT / "src" / "cce" / "cli.py"

PRD_SPAN_SET: frozenset[str] = frozenset({
    "cce.load_spec",
    "cce.clone",
    "cce.parse",
    "cce.measure",
    "cce.score",
})
ALLOWED_SPAN_SET: frozenset[str] = PRD_SPAN_SET | {"cce.write_outputs"}

# Mirrors the design §B.7 parser regex byte-for-byte.
_NAME_RE = re.compile(r"^cce\.[a-z_]+$")


def _extract_span_names(stderr: str) -> set[str]:
    """Span_Gate parser body, lifted from the design §B.7 inline heredoc.

    Treats each ``\\n``-delimited line independently:

      * Lines that fail to parse as a single JSON object are skipped.
      * Lines that parse but are not a ``dict`` are skipped.
      * Lines whose ``name`` field is missing or non-string are skipped.
      * The remaining ``name`` values whose content matches
        ``^cce\\.[a-z_]+$`` are collected into the returned set.
    """
    extracted: set[str] = set()
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        if not _NAME_RE.match(name):
            continue
        extracted.add(name)
    return extracted


def _git_init_fixture_copy(work: Path) -> None:
    """Copy ``simple_python`` into ``work`` and git-init it deterministically.

    The author/committer env vars match the deterministic-fixture protocol
    documented in ``docs/reproductions/README.md`` and used by the
    ``poc-determinism`` workflow. The exact values do not matter for span
    extraction — they only matter for ``record_hash`` byte-stability — but
    using them keeps the fixture-init flow byte-identical to the rest of
    the suite (e.g. ``tests/test_submodule_trap.py``).
    """
    shutil.copytree(SIMPLE_PYTHON_FIXTURE, work, dirs_exist_ok=True)
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
    subprocess.run(
        ["git", "config", "user.email", "cce@example.test"],
        cwd=work,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "CCE Test"],
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


@pytest.fixture(scope="module")
def emitted_span_names(tmp_path_factory: pytest.TempPathFactory) -> set[str]:
    """Run ``cce score`` once and return the extracted ``cce.*`` span names.

    Module-scoped so the three set-level assertions below share a single
    subprocess invocation rather than paying its cost three times.
    The OpenTelemetry SDK must be importable; if it is not (e.g. running
    on a host without the dev lockfile installed), the fixture skips so
    the failure is unambiguous rather than silently passing on the
    ``_NoopTracer`` fallback path.
    """
    pytest.importorskip("opentelemetry.sdk.trace.export")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    work = tmp_path_factory.mktemp("simple_python_repo")
    _git_init_fixture_copy(work)

    out_dir = work.parent / "cce-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Both OTLP_Endpoint_Vars cleared so init_otel selects the
    # ConsoleSpanExporter(out=sys.stderr) branch (Requirement 2.2).
    env = {
        **os.environ,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "cce",
            "score",
            "--spec",
            str(SCORING_SPEC),
            "--repo",
            str(work),
            "--mode",
            "repo",
            "--out",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 0, (
        f"cce score exited {proc.returncode}\n"
        f"--- stderr ---\n{proc.stderr}\n"
        f"--- stdout ---\n{proc.stdout}"
    )

    return _extract_span_names(proc.stderr)


def test_emitted_span_set_equals_allowed_span_set(
    emitted_span_names: set[str],
) -> None:
    """The full set of emitted ``cce.*`` spans equals ``Allowed_Span_Set``.

    Validates: Requirements 1.6, 1.7, 1.8.
    """
    assert emitted_span_names == set(ALLOWED_SPAN_SET), (
        f"emitted span set drift\n"
        f"  emitted    = {sorted(emitted_span_names)!r}\n"
        f"  expected   = {sorted(ALLOWED_SPAN_SET)!r}\n"
        f"  missing    = {sorted(set(ALLOWED_SPAN_SET) - emitted_span_names)!r}\n"
        f"  extraneous = {sorted(emitted_span_names - set(ALLOWED_SPAN_SET))!r}"
    )


def test_no_cce_prepared_repo_span(emitted_span_names: set[str]) -> None:
    """The legacy ``cce.prepared_repo`` span name is not emitted.

    Validates: Requirement 1.10.
    """
    assert "cce.prepared_repo" not in emitted_span_names, (
        f"legacy span name 'cce.prepared_repo' was emitted; "
        f"emitted set = {sorted(emitted_span_names)!r}"
    )


def test_no_cce_analyze_span(emitted_span_names: set[str]) -> None:
    """The legacy ``cce.analyze`` span name is not emitted.

    Validates: Requirement 1.11.
    """
    assert "cce.analyze" not in emitted_span_names, (
        f"legacy span name 'cce.analyze' was emitted; "
        f"emitted set = {sorted(emitted_span_names)!r}"
    )


def test_static_source_has_no_legacy_stage_names() -> None:
    """``src/cce/cli.py`` contains no ``stage_span("prepared_repo"|"analyze")``.

    Defense-in-depth against accidental reintroduction of the legacy span
    names by a future refactor (design §F "tests/test_span_names.py").

    Validates: Requirements 1.10, 1.11.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")
    pattern = re.compile(r'stage_span\(\s*["\'](prepared_repo|analyze)["\']')
    match = pattern.search(source)
    assert match is None, (
        f"src/cce/cli.py contains a legacy stage_span call for "
        f"{match.group(1)!r} at offset {match.start()}; "
        f"this name was removed by tasks 1.5/1.6 and must not be reintroduced"
    )
