"""Workflow-matrix shape and ordering invariants.

Spec: poc-readiness-hard-blockers, task 2.7.
Validates Requirements 1.4, 1.5, 2.1, 2.2, 2.3, 2.6.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DETERMINISM = REPO_ROOT / ".github" / "workflows" / "poc-determinism.yml"
NIGHTLY = REPO_ROOT / ".github" / "workflows" / "nightly-stability.yml"

ALL_FIXTURES = ("simple_python", "simple_typescript", "perf_100k")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _matrix_axes(workflow: dict, job_name: str) -> dict:
    job = workflow["jobs"][job_name]
    return job["strategy"]["matrix"]


def test_deterministic_core_matrix_covers_all_fixtures_and_runners() -> None:
    """deterministic-core covers (3 runners) × (3 fixtures) = 9 cells."""
    workflow = _load(DETERMINISM)
    matrix = _matrix_axes(workflow, "deterministic-core")
    runners = set(matrix["runner-name"])
    fixtures = set(matrix["fixture"])
    assert runners == {"linux-x86_64", "linux-arm64", "macos-arm64"}, runners
    assert fixtures == set(ALL_FIXTURES), fixtures
    expected = set(product(runners, fixtures))
    assert len(expected) == 9


def test_container_isolation_matrix_covers_all_fixtures() -> None:
    """container-isolation covers (2 Linux runners) × (3 fixtures) = 6 cells."""
    workflow = _load(DETERMINISM)
    matrix = _matrix_axes(workflow, "container-isolation")
    runners = set(matrix["runner-name"])
    fixtures = set(matrix["fixture"])
    assert runners == {"linux-x86_64", "linux-arm64"}, runners
    assert fixtures == set(ALL_FIXTURES), fixtures


def test_nightly_matrix_hash_covers_all_fixtures() -> None:
    """nightly-stability::matrix-hash covers (2 Linux runners) × (3 fixtures) = 6 cells."""
    workflow = _load(NIGHTLY)
    matrix = _matrix_axes(workflow, "matrix-hash")
    runners = set(matrix["runner-name"])
    fixtures = set(matrix["fixture"])
    assert runners == {"linux-x86_64", "linux-arm64"}, runners
    assert fixtures == set(ALL_FIXTURES), fixtures


def test_no_verify_digests_false_in_workflows() -> None:
    """No workflow YAML may pass `--verify-digests false`."""
    needle = "--verify-digests false"
    for path in (DETERMINISM, NIGHTLY):
        text = path.read_text(encoding="utf-8")
        assert needle not in text, f"{path.relative_to(REPO_ROOT)} still contains {needle!r}"


def test_streak_tracker_runs_per_fixture_check_before_streak_update() -> None:
    """The per-fixture cross-runner agreement step must precede the
    `Update ops/nightly-streak.json` step, so a fixture-disagreement
    fails the job before the streak counter is incremented."""
    workflow = _load(NIGHTLY)
    steps = workflow["jobs"]["streak-tracker"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    per_fixture_idx = next(
        (i for i, name in enumerate(step_names) if "per-fixture matrix-hash agreement" in name),
        None,
    )
    update_streak_idx = next(
        (i for i, name in enumerate(step_names) if "Update ops/nightly-streak.json" in name),
        None,
    )
    assert per_fixture_idx is not None, f"no per-fixture step in {step_names}"
    assert update_streak_idx is not None, f"no streak-update step in {step_names}"
    assert per_fixture_idx < update_streak_idx, (
        f"per-fixture check (idx {per_fixture_idx}) must run before "
        f"streak update (idx {update_streak_idx})"
    )


def test_deterministic_core_has_frozen_hash_gate() -> None:
    """The deterministic-core job must have a Frozen_Hash_Gate step that
    asserts record_hash matches expected_record_hash.txt."""
    workflow = _load(DETERMINISM)
    steps = workflow["jobs"]["deterministic-core"]["steps"]
    found = any(
        "Frozen_Hash_Gate" in step.get("name", "")
        and "expected_record_hash.txt" in step.get("run", "")
        for step in steps
    )
    assert found, "deterministic-core missing Frozen_Hash_Gate step"


def test_container_isolation_has_frozen_hash_gate() -> None:
    """The container-isolation job must have a Frozen_Hash_Gate step."""
    workflow = _load(DETERMINISM)
    steps = workflow["jobs"]["container-isolation"]["steps"]
    found = any(
        "Frozen_Hash_Gate" in step.get("name", "")
        and "expected_record_hash.txt" in step.get("run", "")
        for step in steps
    )
    assert found, "container-isolation missing Frozen_Hash_Gate step"


def test_matrix_hash_has_frozen_hash_gate() -> None:
    """The nightly matrix-hash job must have a Frozen_Hash_Gate step."""
    workflow = _load(NIGHTLY)
    steps = workflow["jobs"]["matrix-hash"]["steps"]
    found = any(
        "Frozen_Hash_Gate" in step.get("name", "")
        and "expected_record_hash.txt" in step.get("run", "")
        for step in steps
    )
    assert found, "matrix-hash missing Frozen_Hash_Gate step"


def test_compare_hashes_runs_per_fixture_agreement_loop() -> None:
    """compare-hashes must loop over all three fixtures, not glob globally."""
    workflow = _load(DETERMINISM)
    steps = workflow["jobs"]["compare-hashes"]["steps"]
    step_runs = [s.get("run", "") for s in steps]
    combined = "\n".join(step_runs)
    for fixture in ALL_FIXTURES:
        assert fixture in combined, f"compare-hashes does not mention {fixture}"
    assert "for fixture in" in combined, "compare-hashes lacks a per-fixture loop"


# ---------------------------------------------------------------------------
# PREQ-O-1 Span_Gate workflow shape (spec preqo1-span-reconciliation, task 3.5)
# ---------------------------------------------------------------------------
# Validates: Requirements 4.1, 4.8 of spec preqo1-span-reconciliation, and
# the cross-implementation byte-equality contract from design §B.7 / §"Out
# of Scope" — the inline Python heredoc parser in
# ``.github/workflows/poc-determinism.yml::span-gate`` and the
# ``_extract_span_names`` helper in ``tests/test_otel_properties.py`` MUST
# have byte-identical inner-loop bodies after whitespace normalisation.

import ast
import re
import textwrap

TEST_OTEL_PROPERTIES = REPO_ROOT / "tests" / "test_otel_properties.py"


def _span_gate_job() -> dict:
    """Return the parsed ``span-gate`` job from poc-determinism.yml."""
    workflow = _load(DETERMINISM)
    assert "span-gate" in workflow["jobs"], (
        f"missing top-level job 'span-gate' in {DETERMINISM.relative_to(REPO_ROOT)}: "
        f"jobs={sorted(workflow['jobs'])}"
    )
    return workflow["jobs"]["span-gate"]


def _span_gate_cce_run_step() -> dict:
    """Return the ``Run cce score and capture stderr`` step of span-gate."""
    job = _span_gate_job()
    matches = [s for s in job["steps"] if s.get("name") == "Run cce score and capture stderr"]
    assert len(matches) == 1, (
        f"expected exactly one 'Run cce score and capture stderr' step in span-gate, "
        f"got {len(matches)} (step names: {[s.get('name') for s in job['steps']]})"
    )
    return matches[0]


def _span_gate_parser_step() -> dict:
    """Return the Python-heredoc parser step (``Span_Gate — assert ...``)."""
    job = _span_gate_job()
    matches = [
        s for s in job["steps"] if s.get("name", "").startswith("Span_Gate — assert")
    ]
    assert len(matches) == 1, (
        f"expected exactly one 'Span_Gate — assert ...' step in span-gate, "
        f"got {len(matches)} (step names: {[s.get('name') for s in job['steps']]})"
    )
    return matches[0]


def _normalise_body(text: str) -> str:
    """Strip leading/trailing whitespace per line; drop blank lines.

    Per spec preqo1-span-reconciliation task 3.5: the cross-implementation
    byte-equality test tolerates whitespace differences (the helper sits
    at a different indentation level than the heredoc body) but nothing
    else.
    """
    return "\n".join(
        stripped
        for line in text.splitlines()
        if (stripped := line.strip())
    )


def _slice_for_body(source: str, for_node: ast.For) -> str:
    """Return the original-source text spanning ``for_node``'s body."""
    src_lines = source.splitlines()
    start = for_node.body[0].lineno - 1
    end = for_node.body[-1].end_lineno
    return "\n".join(src_lines[start:end])


def _find_parser_loop(tree: ast.AST) -> ast.For:
    """Locate the parser-loop ``for`` node in an AST subtree.

    The parser loop is the unique ``for`` node whose iteration target is
    the bare name ``line`` (matching both the helper's ``for line in
    lines:`` and the heredoc's ``for line in stderr.splitlines():``).
    Filtering by target — instead of by appearance order — keeps the
    test resilient to additional diagnostic loops elsewhere in either
    source.
    """
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "line"
    ]
    assert len(candidates) == 1, (
        f"expected exactly one `for line in ...` loop, got {len(candidates)}"
    )
    return candidates[0]


def _extract_helper_loop_body() -> str:
    """Extract the inner-loop body of ``_extract_span_names`` from
    ``tests/test_otel_properties.py``.

    Uses AST to locate the function and its parser ``for`` loop, then
    slices the original source by the AST line numbers so the returned
    text is the verbatim loop body — exactly the bytes we want to
    compare against the workflow heredoc.
    """
    source = TEST_OTEL_PROPERTIES.read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_span_names"
    ]
    assert len(funcs) == 1, (
        f"expected exactly one _extract_span_names function in "
        f"{TEST_OTEL_PROPERTIES.relative_to(REPO_ROOT)}, got {len(funcs)}"
    )
    return _slice_for_body(source, _find_parser_loop(funcs[0]))


def _extract_workflow_loop_body() -> str:
    """Extract the inner-loop body of the Span_Gate Python heredoc.

    Reads the YAML, locates the ``Span_Gate — assert ...`` step, finds the
    ``<<'PY' ... PY`` heredoc inside its ``run`` block, dedents the
    contained Python source, AST-parses it to find the parser ``for``
    loop, and slices the dedented heredoc source by the AST line numbers.
    """
    step = _span_gate_parser_step()
    run_text = step["run"]
    match = re.search(
        r"<<'PY'\n(.*?)\n[ \t]*PY[ \t]*(?:\n|$)",
        run_text,
        flags=re.DOTALL,
    )
    assert match is not None, (
        "Python heredoc (<<'PY' ... PY) not found in Span_Gate parser step"
    )
    heredoc_src = textwrap.dedent(match.group(1))
    tree = ast.parse(heredoc_src)
    return _slice_for_body(heredoc_src, _find_parser_loop(tree))


def test_span_gate_job_exists() -> None:
    """``poc-determinism.yml`` must declare a top-level ``span-gate`` job."""
    workflow = _load(DETERMINISM)
    assert "span-gate" in workflow["jobs"], (
        f"missing top-level job 'span-gate' in "
        f"{DETERMINISM.relative_to(REPO_ROOT)}: jobs={sorted(workflow['jobs'])}"
    )


def test_span_gate_runs_on_ubuntu_24_04() -> None:
    """``span-gate.runs-on`` must be ``ubuntu-24.04`` (Requirement 4.8)."""
    job = _span_gate_job()
    assert job["runs-on"] == "ubuntu-24.04", (
        f"span-gate must run on ubuntu-24.04 (linux-x86_64 per Requirement 4.8); "
        f"got {job['runs-on']!r}"
    )


def test_span_gate_has_5_minute_step_timeout() -> None:
    """The ``Run cce score`` step has ``timeout-minutes: 5`` (Requirement 4.1)."""
    step = _span_gate_cce_run_step()
    assert step.get("timeout-minutes") == 5, (
        f"'Run cce score and capture stderr' step must set timeout-minutes: 5 "
        f"(Requirement 4.1, 300 s); got {step.get('timeout-minutes')!r}"
    )


def test_span_gate_clears_both_endpoint_env_vars() -> None:
    """The ``Run cce score`` step clears both OTLP_Endpoint_Vars to ``""``.

    With both endpoint variables set to the empty string, ``init_otel``
    selects the Console_Exporter branch (per the glossary definition of
    ``OTLP_Endpoint_Vars`` — values empty after strip are treated as
    unset). This is what makes the Span_Gate parse stderr at all.
    """
    step = _span_gate_cce_run_step()
    env = step.get("env") or {}
    assert env.get("OTEL_EXPORTER_OTLP_ENDPOINT") == "", (
        f"step must set OTEL_EXPORTER_OTLP_ENDPOINT: \"\" so the "
        f"Console_Exporter branch is exercised; got "
        f"{env.get('OTEL_EXPORTER_OTLP_ENDPOINT')!r}"
    )
    assert env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") == "", (
        f"step must set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: \"\" so the "
        f"Console_Exporter branch is exercised; got "
        f"{env.get('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')!r}"
    )


def test_span_gate_parser_matches_test_helper() -> None:
    """Span_Gate heredoc parser body == ``_extract_span_names`` body (bytes).

    The cross-implementation contract from design §B.7 / §"Out of Scope":
    the inline Python heredoc inside the ``Span_Gate — assert ...`` step
    of ``poc-determinism.yml`` and the ``_extract_span_names`` helper in
    ``tests/test_otel_properties.py`` MUST share a byte-identical inner
    loop body after whitespace normalisation (strip leading/trailing
    whitespace per line, drop blank lines). Drift between the two would
    silently invalidate Property 4 (parser correctness on arbitrary
    stderr inputs).
    """
    helper_body = _normalise_body(_extract_helper_loop_body())
    workflow_body = _normalise_body(_extract_workflow_loop_body())

    assert helper_body == workflow_body, (
        "Span_Gate parser drift: workflow heredoc and _extract_span_names "
        "helper must have byte-identical inner-loop bodies (after stripping "
        "per-line whitespace and dropping blank lines). See spec "
        "preqo1-span-reconciliation, design §B.7.\n"
        "--- helper (tests/test_otel_properties.py::_extract_span_names) ---\n"
        f"{helper_body}\n"
        "--- workflow (.github/workflows/poc-determinism.yml::span-gate) ---\n"
        f"{workflow_body}"
    )
