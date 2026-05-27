# Feature: preqo1-span-reconciliation, Property 2 (reduced form): parse-then-measure equivalence
"""Property tests for PREQ-O-1 span reconciliation.

Each property is implemented as a section delimited by a header comment
of the form ``# Property <N> ... Validates: Requirements ...`` so a
reviewer can locate any property by string-search. Subsequent tasks
append additional sections to this file; new properties SHOULD reuse
the imports at the top of the module and add their own header comment
in the same shape.

Currently implemented:
  * Property 2 (reduced form): byte-equivalence of ``analyse_repo`` and
    ``measure_metrics(parse_repo(...))`` over the two committed fixture
    trees ``simple_python`` and ``simple_typescript``. Validates
    Requirements 1.3, 1.4 and reduces toward Property 2 (full form) in
    task 3.3 of this spec.

  * Property 4 (task 2.3): ``Span_Gate`` parser correctness on arbitrary
    stderr inputs. Validates Requirement 4.2.
  * Property 3 (task 2.2): ``init_otel`` exporter-selection function
    purity. Validates Requirements 2.1, 2.2, 2.5, 2.9.
  * Property 5 (task 3.2): stdout discipline under the four-state OTLP
    endpoint matrix. Validates Requirements 5.1, 5.5, 5.6, 6.14.
  * Property 2 (full form, task 3.3): ``record_hash`` invariance under
    exporter choice and SDK presence. Validates Requirements 6.1, 6.3,
    3.8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cce.analyzer import analyse_repo, measure_metrics, parse_repo

# ---------------------------------------------------------------------------
# Module-wide constants
# ---------------------------------------------------------------------------

# Anchor every fixture lookup at the repository root rather than the
# current working directory so the suite passes under both ``pytest`` and
# ``uv run pytest`` invocations from any subdirectory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Property 2 (reduced form): parse-then-measure equivalence
# ---------------------------------------------------------------------------
# Validates: Requirements 1.3, 1.4.
#
# For every Golden_Fixtures entry G in (simple_python, simple_typescript)
# we assert that the legacy single-pass call
#
#     analyse_repo(repo_path)
#
# is byte-for-byte identical to the new two-step pipeline
#
#     measure_metrics(parse_repo(repo_path))
#
# as a ``(raw_metrics, raw_payload)`` tuple. Both halves are checked:
#
#   * ``raw_metrics`` is a flat ``dict[str, str]``; Python's ``==`` is a
#     sufficient byte-level comparison since both sides are produced by
#     the same code path with the same insertion order.
#   * ``raw_payload`` nests lists of per-file dicts and a summary dict;
#     the design specifies a ``json.dumps(..., sort_keys=True)``
#     round-trip as the stable comparison key. We use the most
#     deterministic serialiser settings available (``sort_keys=True``,
#     no whitespace) so any structural drift between the wrapper and
#     the split helpers fails this test deterministically rather than
#     hiding behind insertion-order luck.
#
# This is the reduced form of Property 2 — Hypothesis is not needed
# because the input space is exactly the two committed fixture trees.
# Task 3.3 extends to the full Property 2 form (``record_hash``
# invariance across the OTLP / SDK state matrix).

_GOLDEN_FIXTURES_PROPERTY_2_REDUCED: tuple[str, ...] = (
    "simple_python",
    "simple_typescript",
)


def _stable_payload_key(payload: object) -> str:
    """Return a stable string key for comparing nested ``raw_payload``.

    Uses ``sort_keys=True`` so insertion-order differences at any
    nesting depth cannot mask a substantive byte-level difference, and
    the most compact separators so any whitespace drift is also caught.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("fixture_name", _GOLDEN_FIXTURES_PROPERTY_2_REDUCED)
def test_property_2_reduced_parse_then_measure_equals_analyse_repo(
    fixture_name: str,
) -> None:
    """``analyse_repo == measure_metrics(parse_repo(...))`` byte-for-byte.

    Validates: Requirements 1.3, 1.4.
    """
    repo_path = _FIXTURES_ROOT / fixture_name
    assert repo_path.is_dir(), f"missing committed fixture: {repo_path}"

    direct_metrics, direct_payload = analyse_repo(repo_path)
    split_metrics, split_payload = measure_metrics(parse_repo(repo_path))

    # raw_metrics half: flat dict[str, str], dict equality is byte-level.
    assert direct_metrics == split_metrics, (
        f"raw_metrics drift between analyse_repo and "
        f"measure_metrics(parse_repo(...)) for fixture {fixture_name!r}"
    )

    # raw_payload half: stable JSON serialisation pins byte-equality
    # regardless of nested-dict insertion order.
    assert _stable_payload_key(direct_payload) == _stable_payload_key(split_payload), (
        f"raw_payload drift between analyse_repo and "
        f"measure_metrics(parse_repo(...)) for fixture {fixture_name!r}"
    )

    # Tuple-level cross-check: the full (raw_metrics, raw_payload)
    # return value is what cli.py and tests/test_analyzer.py consume,
    # so we lock byte-identity at the tuple level too.
    assert _stable_payload_key((direct_metrics, direct_payload)) == _stable_payload_key(
        (split_metrics, split_payload)
    )


# ---------------------------------------------------------------------------
# Property 4: Span_Gate parser correctness
# ---------------------------------------------------------------------------
# Feature: preqo1-span-reconciliation, Property 4: Span_Gate parser correctness
# Validates: Requirement 4.2.
#
# The Span_Gate CI step in ``.github/workflows/poc-determinism.yml`` parses
# the captured stderr of a ``cce score`` run line-by-line and extracts the
# set of ``cce.*`` span names from every line that (a) parses as a single
# JSON object, (b) is a dict, (c) has a string-valued ``name`` field, and
# (d) whose ``name`` matches ``^cce\.[a-z_]+$``. Lines that fail any of
# these checks are silently skipped without raising. Requirement 4.2 fixes
# this contract.
#
# This section duplicates the Span_Gate parser into a private helper
# ``_extract_span_names(lines)`` whose inner loop body is byte-for-byte
# identical to the inline Python heredoc in the workflow YAML (the
# top-level wrapping differs by signature only — the heredoc reads from a
# file then calls ``str.splitlines()``; the helper accepts an already-split
# ``list[str]`` directly). The duplication is intentional per the design
# §B.7 and Out-of-Scope notes; task 3.5 in the same spec asserts the
# byte-equality of the two implementations under whitespace normalisation.
#
# We then exercise the helper with Hypothesis at
# ``max_examples=200, deadline=None`` per design §F using a ``@composite``
# strategy that mixes:
#   * well-formed JSON objects with PRD-shaped ``cce.<lower_under>`` names,
#   * well-formed JSON objects with non-matching string names (out-of-set
#     prefixes, uppercase letters, digits, dashes, empty),
#   * well-formed JSON objects with non-string ``name`` fields
#     (``None``, integers, lists, dicts),
#   * well-formed JSON objects with no ``name`` field at all,
#   * well-formed JSON arrays / strings / numbers / null at top-level
#     (i.e. parses as JSON but is not a dict),
#   * malformed JSON fragments that ``json.loads`` rejects,
#   * empty strings and pure-whitespace strings,
#   * arbitrary "noise" lines (free-form text, log-message-shaped lines).
#
# The reference oracle ``_oracle_extract_span_names`` is an independently
# coded pure-Python implementation of the same four parsing rules. The
# property asserts (a) the helper never raises on any input list and (b)
# the helper's output equals the oracle's output for every generated list.

import re

from hypothesis import given, settings
from hypothesis import strategies as st

# ``NAME_RE`` mirrors the workflow YAML's ``re.compile(r"^cce\.[a-z_]+$")``
# verbatim. The regex is intentionally tight: only ASCII lowercase letters
# and underscores are accepted in the suffix; ``cce.`` itself is the only
# required literal prefix.
NAME_RE = re.compile(r"^cce\.[a-z_]+$")


def _extract_span_names(lines: list[str]) -> set[str]:
    """Span_Gate parser body, lifted from the workflow YAML.

    The inner loop body (from ``line = line.strip()`` through
    ``extracted.add(name)``) MUST be byte-for-byte identical to the
    inline Python heredoc in
    ``.github/workflows/poc-determinism.yml::span-gate``. Task 3.5 in
    this spec asserts that byte-equality under whitespace normalisation.
    """
    extracted: set[str] = set()
    for line in lines:
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
        if not NAME_RE.match(name):
            continue
        extracted.add(name)
    return extracted


def _oracle_extract_span_names(lines: list[str]) -> set[str]:
    """Independently coded oracle for the Span_Gate parsing rules.

    The implementation deliberately uses a different control-flow shape
    from ``_extract_span_names`` (filter-first, then accept) so that
    structural bugs in the helper are not silently mirrored into the
    oracle. Both implementations must agree on the same four rules:

      1. Strip ASCII whitespace from each line; drop empty results.
      2. The line must parse via ``json.loads`` without raising.
      3. The parsed value must be a ``dict`` instance.
      4. The dict's ``name`` field must be a ``str`` matching
         ``^cce\\.[a-z_]+$``.
    """
    pattern = re.compile(r"^cce\.[a-z_]+$")
    out: set[str] = set()
    for raw in lines:
        candidate = raw.strip()
        if candidate == "":
            continue
        try:
            parsed = json.loads(candidate)
        except Exception:  # noqa: BLE001  -- oracle uses broad accept-by-rejection
            # ``json.loads`` raises ``json.JSONDecodeError`` (a subclass
            # of ``ValueError``) on malformed input. We swallow broadly
            # in the oracle so any implementation drift in the helper's
            # narrower ``(ValueError, json.JSONDecodeError)`` clause
            # would surface as an oracle/helper disagreement.
            continue
        if type(parsed) is not dict:  # noqa: E721  -- explicit non-subclass check
            continue
        name_value = parsed.get("name", None)
        if not isinstance(name_value, str):
            continue
        # NOTE: ``re.match(r"...$", s)`` matches at end-of-string OR
        # immediately before a trailing newline (Python regex quirk;
        # see https://docs.python.org/3/library/re.html#re.match). The
        # workflow YAML's heredoc uses ``NAME_RE.match(name)`` so the
        # oracle must encode the same quirk to faithfully describe the
        # helper's parsing rule. Using ``fullmatch`` here would over-
        # constrain the oracle and produce false-positive disagreements
        # on inputs like ``"cce.foo\n"``.
        if pattern.match(name_value) is None:
            continue
        out.add(name_value)
    return out


# ---------------------------------------------------------------------------
# Hypothesis strategies for arbitrary stderr-shaped lines
# ---------------------------------------------------------------------------

# A small alphabet of PRD-shaped name suffixes plus a few near-miss values.
# The PRD-shaped values are drawn from ``Allowed_Span_Set``; the near-miss
# values are intentionally selected to exercise each failure branch of
# ``NAME_RE.match``: digits, uppercase, dashes, dots, empty, missing prefix.
_PRD_SHAPED_NAMES = st.sampled_from([
    "cce.load_spec",
    "cce.clone",
    "cce.parse",
    "cce.measure",
    "cce.score",
    "cce.write_outputs",
    # Other well-formed members of the regex's image — not in the
    # Allowed_Span_Set, but still PRD-shaped. The helper must collect
    # them; the workflow's separate set-membership step would later
    # flag them as extraneous, but that is out of scope for Property 4.
    "cce.foo",
    "cce.a",
    "cce.bar_baz_qux",
])

_NEAR_MISS_NAMES = st.sampled_from([
    "",                # empty
    "cce.",            # missing suffix
    ".cce.foo",        # leading dot
    "cce.Foo",         # uppercase
    "cce.foo1",        # digit
    "cce.foo-bar",     # dash
    "cce.foo.bar",     # extra dot
    "ccex.foo",        # wrong prefix
    "Cce.foo",         # uppercase prefix
    "cce_foo",         # underscore instead of dot
    " cce.foo ",       # leading/trailing whitespace inside the name
    "cce.foo\n",       # embedded newline
    "load_spec",       # missing prefix
])

_NON_STRING_NAME_VALUES = st.sampled_from([
    None,
    0,
    1,
    -1,
    1.5,
    True,
    False,
    [],
    ["cce.load_spec"],
    {},
    {"nested": "cce.score"},
])

# Free-form noise text that should never be accepted as a span name —
# used both as bare lines and as the content of well-formed JSON objects'
# unrelated fields.
_NOISE_TEXT = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x7E,
        # Drop double-quote and backslash so that, when this text shows
        # up as a JSON-string field value, we do not have to re-escape it
        # by hand inside the synthetic JSON objects below.
        blacklist_characters='"\\',
    ),
    min_size=0,
    max_size=40,
)


@st.composite
def _well_formed_object_with_prd_name(draw: st.DrawFn) -> str:
    """Synthetic JSON object whose ``name`` matches the PRD regex."""
    name = draw(_PRD_SHAPED_NAMES)
    extras: dict[str, object] = {
        # Throw in some unrelated fields the parser must ignore.
        "context": {"trace_id": "0x" + draw(st.text(
            alphabet=st.characters(
                min_codepoint=ord("0"),
                max_codepoint=ord("9"),
                whitelist_characters="abcdef",
            ),
            min_size=32,
            max_size=32,
        ))},
        "kind": "SpanKind.INTERNAL",
        "noise": draw(_NOISE_TEXT),
    }
    obj: dict[str, object] = {"name": name, **extras}
    return json.dumps(obj, ensure_ascii=False)


@st.composite
def _well_formed_object_with_near_miss_name(draw: st.DrawFn) -> str:
    """Synthetic JSON object whose ``name`` is a string but fails the regex."""
    name = draw(_NEAR_MISS_NAMES)
    obj: dict[str, object] = {"name": name, "noise": draw(_NOISE_TEXT)}
    return json.dumps(obj, ensure_ascii=False)


@st.composite
def _well_formed_object_with_non_string_name(draw: st.DrawFn) -> str:
    """Synthetic JSON object whose ``name`` field is not a string."""
    name = draw(_NON_STRING_NAME_VALUES)
    obj: dict[str, object] = {"name": name, "noise": draw(_NOISE_TEXT)}
    return json.dumps(obj, ensure_ascii=False)


@st.composite
def _well_formed_object_without_name(draw: st.DrawFn) -> str:
    """Synthetic JSON object with no ``name`` field at all."""
    obj: dict[str, object] = {
        "kind": "SpanKind.INTERNAL",
        "noise": draw(_NOISE_TEXT),
    }
    return json.dumps(obj, ensure_ascii=False)


@st.composite
def _well_formed_non_dict_json(draw: st.DrawFn) -> str:
    """Top-level JSON value that parses but is not a dict."""
    return draw(st.sampled_from([
        "null",
        "true",
        "false",
        "0",
        "1",
        "-1",
        "1.5",
        '"cce.load_spec"',          # string at top level
        "[]",
        '["cce.load_spec"]',        # array containing a PRD-shaped name
        '[{"name":"cce.load_spec"}]',
    ]))


@st.composite
def _malformed_json(draw: st.DrawFn) -> str:
    """Strings that ``json.loads`` rejects with ``json.JSONDecodeError``."""
    return draw(st.sampled_from([
        "{",
        "}",
        "[",
        "{not json",
        '{"name": "cce.foo"',       # missing closing brace
        '{"name": cce.foo}',        # unquoted value
        "{'name': 'cce.foo'}",      # single quotes
        "undefined",
        "NaN",
        "Infinity",
        "-Infinity",
        "{,}",
        "[,]",
    ]))


@st.composite
def _whitespace_or_empty(draw: st.DrawFn) -> str:
    """Empty or whitespace-only line."""
    return draw(st.sampled_from(["", " ", "  ", "\t", "  \t  ", "\v", "\f"]))


@st.composite
def _noise_line(draw: st.DrawFn) -> str:
    """Free-form noise line — log-shaped or arbitrary text."""
    return draw(st.one_of(
        _NOISE_TEXT,
        st.sampled_from([
            "init_otel: RuntimeError: boom",
            "cce.load_spec: 12 ms",
            "cce.total: 345 ms",
            "Traceback (most recent call last):",
            "sha256:" + "a" * 64,
        ]),
    ))


@st.composite
def _candidate_line(draw: st.DrawFn) -> str:
    """One line of the synthetic stderr stream.

    Drawn from the union of all line shapes the Span_Gate parser must
    handle. The composition is biased toward well-formed JSON objects so
    each Hypothesis example has a non-trivial chance of producing at
    least one collected span name.
    """
    return draw(st.one_of(
        _well_formed_object_with_prd_name(),
        _well_formed_object_with_near_miss_name(),
        _well_formed_object_with_non_string_name(),
        _well_formed_object_without_name(),
        _well_formed_non_dict_json(),
        _malformed_json(),
        _whitespace_or_empty(),
        _noise_line(),
    ))


@st.composite
def _candidate_lines_list(draw: st.DrawFn) -> list[str]:
    """A list of synthetic stderr lines.

    Bounded at 64 lines per example so generation cost stays linear
    while still exercising a realistic mix of accepted, rejected, and
    malformed lines per example.
    """
    return draw(st.lists(_candidate_line(), min_size=0, max_size=64))


@settings(max_examples=200, deadline=None)
@given(lines=_candidate_lines_list())
def test_property_4_span_gate_parser_matches_oracle(lines: list[str]) -> None:
    """``_extract_span_names(lines) == _oracle_extract_span_names(lines)``.

    Validates: Requirement 4.2.

    Asserts (a) the helper never raises on any input list, and (b) the
    helper's output equals the oracle's output for every generated
    ``list[str]``.
    """
    # (a) parser never raises — captured here so a hypothetical future
    # bug that panics on a specific input shape surfaces as a test
    # failure rather than as an uncaught exception escaping the harness.
    try:
        helper_out = _extract_span_names(lines)
    except Exception as exc:  # pragma: no cover  -- only fires on regression
        raise AssertionError(
            f"_extract_span_names raised {exc.__class__.__name__}: {exc!r} "
            f"on input lines={lines!r}"
        ) from exc

    # (b) helper output equals oracle output.
    oracle_out = _oracle_extract_span_names(lines)
    assert helper_out == oracle_out, (
        f"Span_Gate parser disagrees with oracle:\n"
        f"  lines    = {lines!r}\n"
        f"  helper   = {sorted(helper_out)!r}\n"
        f"  oracle   = {sorted(oracle_out)!r}\n"
        f"  helper-only = {sorted(helper_out - oracle_out)!r}\n"
        f"  oracle-only = {sorted(oracle_out - helper_out)!r}"
    )


# ---------------------------------------------------------------------------
# Smoke examples — sanity-check the helper on hand-written inputs that
# would be tedious to recover from a Hypothesis counterexample.
# ---------------------------------------------------------------------------

def test_property_4_extract_span_names_collects_prd_set_from_well_formed_lines() -> None:
    """The helper collects every PRD-shaped name from a clean JSON-line stream.

    Validates: Requirement 4.2.
    """
    lines = [
        json.dumps({"name": "cce.load_spec"}),
        json.dumps({"name": "cce.clone"}),
        json.dumps({"name": "cce.parse"}),
        json.dumps({"name": "cce.measure"}),
        json.dumps({"name": "cce.score"}),
        json.dumps({"name": "cce.write_outputs"}),
    ]
    assert _extract_span_names(lines) == {
        "cce.load_spec",
        "cce.clone",
        "cce.parse",
        "cce.measure",
        "cce.score",
        "cce.write_outputs",
    }


def test_property_4_extract_span_names_skips_malformed_and_noise() -> None:
    """Malformed JSON, non-dict JSON, and noise are silently dropped.

    Validates: Requirement 4.2.
    """
    lines = [
        "",
        "   ",
        "{",                                   # malformed
        "[1, 2, 3]",                           # non-dict
        "null",                                # non-dict
        '"cce.score"',                         # non-dict (string)
        json.dumps({"kind": "x"}),             # missing name
        json.dumps({"name": None}),            # non-string name
        json.dumps({"name": 42}),              # non-string name
        json.dumps({"name": "cce.Foo"}),       # uppercase fails regex
        json.dumps({"name": "cce.foo1"}),      # digit fails regex
        json.dumps({"name": "load_spec"}),     # missing prefix
        "init_otel: RuntimeError: boom",       # noise
        json.dumps({"name": "cce.parse"}),     # accepted
    ]
    assert _extract_span_names(lines) == {"cce.parse"}


def test_property_4_extract_span_names_strips_surrounding_whitespace() -> None:
    """The helper strips leading/trailing whitespace before parsing.

    Validates: Requirement 4.2.
    """
    payload = json.dumps({"name": "cce.load_spec"})
    lines = [f"   {payload}\t", f"\n{payload}\n"]
    assert _extract_span_names(lines) == {"cce.load_spec"}


# ---------------------------------------------------------------------------
# Property 3: init_otel exporter-selection function purity
# ---------------------------------------------------------------------------
# Feature: preqo1-span-reconciliation, Property 3: init_otel exporter-selection function purity
# Validates: Requirements 2.1, 2.2, 2.5, 2.9.
#
# For any ``OTLP_Endpoint_Vars`` state S, the class of the exporter installed
# by ``init_otel()`` and the keyword arguments passed to its constructor MUST
# be exact functions of S alone, with the mapping fixed by the design
# §"Property 3" table:
#
#   state S                            installed class       constructor kwargs
#   ---------------------------------  --------------------  ----------------------------------
#   both unset / both whitespace-only  ConsoleSpanExporter   {"out": sys.stderr}
#   only TRACES set                    OTLPSpanExporter      {"endpoint": <stripped TRACES>}
#   only generic set                   OTLPSpanExporter      {"endpoint": <stripped generic>}
#   both set                           OTLPSpanExporter      {"endpoint": <stripped TRACES>}
#
# The output MUST NOT depend on any other process state, command-line flag,
# or file on disk. The idempotent guard means N>1 calls return early before
# consulting S; this property quantifies only over the **first** call in a
# process lifetime, simulated by resetting ``cce.otel._INITIALISED = False``.
#
# Implementation strategy:
#
# Because ``init_otel`` performs its SDK imports inside its own ``try:``
# block at call time, we patch the already-loaded SDK modules so the
# ``from opentelemetry.sdk.trace.export import ConsoleSpanExporter`` lookup
# inside ``init_otel`` resolves to a spy class. Each spy class records
# ``(class, kwargs)`` into a per-test ``recorded`` list at construction.
# ``BatchSpanProcessor`` is also replaced with an inert spy so the real one
# does not spawn a worker thread; ``trace.set_tracer_provider`` is replaced
# with a no-op so we do not pollute the global tracer provider across tests.
#
# This is a finite, four-state input space (plus whitespace variants), so
# ``pytest.parametrize`` is the right tool — Hypothesis would only add cost.

from typing import Any

_PROPERTY_3_STATES: list[dict[str, Any]] = [
    # Row 1: both unset → ConsoleSpanExporter(out=sys.stderr)
    {
        "id": "both_unset",
        "traces": None,
        "generic": None,
        "expected_kind": "console",
        "expected_endpoint": None,
    },
    # Row 1 variant: both whitespace-only → treated as unset by _stripped_env
    {
        "id": "both_whitespace",
        "traces": "   ",
        "generic": "\t  \n",
        "expected_kind": "console",
        "expected_endpoint": None,
    },
    # Row 1 variant: TRACES whitespace-only, generic missing
    {
        "id": "traces_whitespace_generic_unset",
        "traces": "   ",
        "generic": None,
        "expected_kind": "console",
        "expected_endpoint": None,
    },
    # Row 1 variant: TRACES missing, generic whitespace-only
    {
        "id": "traces_unset_generic_whitespace",
        "traces": None,
        "generic": "  \t",
        "expected_kind": "console",
        "expected_endpoint": None,
    },
    # Row 2: only TRACES set → OTLPSpanExporter(endpoint=<stripped TRACES>)
    {
        "id": "only_traces_set",
        "traces": "http://collector.local:4318/v1/traces",
        "generic": None,
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318/v1/traces",
    },
    # Row 2 variant: TRACES set with surrounding whitespace → stripped before use
    {
        "id": "only_traces_set_with_padding",
        "traces": "  http://collector.local:4318/v1/traces\n",
        "generic": None,
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318/v1/traces",
    },
    # Row 2 variant: TRACES set, generic whitespace-only → still TRACES wins
    {
        "id": "traces_set_generic_whitespace",
        "traces": "http://collector.local:4318/v1/traces",
        "generic": "   ",
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318/v1/traces",
    },
    # Row 3: only generic set → OTLPSpanExporter(endpoint=<stripped generic>)
    {
        "id": "only_generic_set",
        "traces": None,
        "generic": "http://collector.local:4318",
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318",
    },
    # Row 3 variant: generic with surrounding whitespace → stripped before use
    {
        "id": "only_generic_set_with_padding",
        "traces": None,
        "generic": "\thttp://collector.local:4318  ",
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318",
    },
    # Row 3 variant: TRACES whitespace-only, generic set → generic wins because
    # _stripped_env collapses TRACES to None
    {
        "id": "traces_whitespace_generic_set",
        "traces": "   ",
        "generic": "http://collector.local:4318",
        "expected_kind": "otlp",
        "expected_endpoint": "http://collector.local:4318",
    },
    # Row 4: both set → TRACES wins (precedence rule)
    {
        "id": "both_set",
        "traces": "http://traces.local:4318/v1/traces",
        "generic": "http://generic.local:4318",
        "expected_kind": "otlp",
        "expected_endpoint": "http://traces.local:4318/v1/traces",
    },
    # Row 4 variant: both set with surrounding whitespace → stripped TRACES wins
    {
        "id": "both_set_with_padding",
        "traces": "  http://traces.local:4318/v1/traces  ",
        "generic": "  http://generic.local:4318  ",
        "expected_kind": "otlp",
        "expected_endpoint": "http://traces.local:4318/v1/traces",
    },
]


@pytest.mark.parametrize("state", _PROPERTY_3_STATES, ids=lambda s: s["id"])
def test_property_3_init_otel_selection_purity(
    state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``init_otel`` chooses the exporter class and endpoint as a pure
    function of ``OTLP_Endpoint_Vars`` per the design §"Property 3" table.

    Validates: Requirements 2.1, 2.2, 2.5, 2.9.
    """
    # Skip cleanly if the OTel SDK is unavailable in this environment. The
    # production / dev images install it via Requirement 3; locally we
    # tolerate its absence so the rest of this module's properties remain
    # runnable.
    sdk_export = pytest.importorskip("opentelemetry.sdk.trace.export")
    otlp_te = pytest.importorskip(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    )
    trace_module = pytest.importorskip("opentelemetry.trace")

    import sys as _sys  # local alias keeps the assertion site self-explanatory

    import cce.otel as cce_otel

    # ------------------------------------------------------------------
    # Spy classes — record (class, kwargs) at construction time. A single
    # ``recorded`` list is shared between both spies so we can later assert
    # that exactly one exporter constructor was invoked across the whole
    # ``init_otel`` body.
    # ------------------------------------------------------------------
    recorded: list[tuple[type, dict[str, Any]]] = []

    class _SpyConsoleSpanExporter:
        """Spy replacement for ``opentelemetry.sdk.trace.export.ConsoleSpanExporter``."""

        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyConsoleSpanExporter, dict(kwargs)))

        # Surface the methods ``BatchSpanProcessor`` may invoke during
        # shutdown / flush so any plumbing call from a real BatchSpanProcessor
        # is non-fatal. None of these are exercised by the assertions below.
        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyOTLPSpanExporter:
        """Spy replacement for ``opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter``."""

        def __init__(self, **kwargs: Any) -> None:
            recorded.append((_SpyOTLPSpanExporter, dict(kwargs)))

        def export(self, _spans: object) -> int:
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, _timeout_millis: int = 30000) -> bool:
            return True

    class _SpyBatchSpanProcessor:
        """Inert ``BatchSpanProcessor`` replacement.

        The real ``BatchSpanProcessor`` spawns a daemon worker thread on
        construction; we want hermetic, side-effect-free tests, so we
        replace it with a no-op shim. ``init_otel`` only needs the
        constructor signature ``(exporter)`` and an object accepted by
        ``TracerProvider.add_span_processor(...)`` — which accepts any
        object exposing the standard processor protocol.
        """

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

    # Patch the already-loaded SDK modules so ``init_otel``'s own ``from
    # opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor``
    # and ``from opentelemetry.exporter.otlp.proto.http.trace_exporter import
    # OTLPSpanExporter`` resolve to our spies. ``monkeypatch.setattr``
    # records the originals and restores them on test teardown.
    monkeypatch.setattr(sdk_export, "ConsoleSpanExporter", _SpyConsoleSpanExporter)
    monkeypatch.setattr(sdk_export, "BatchSpanProcessor", _SpyBatchSpanProcessor)
    monkeypatch.setattr(otlp_te, "OTLPSpanExporter", _SpyOTLPSpanExporter)

    # Avoid polluting the global tracer provider across tests; init_otel's
    # call to ``trace.set_tracer_provider(provider)`` becomes a no-op.
    monkeypatch.setattr(trace_module, "set_tracer_provider", lambda _provider: None)

    # ------------------------------------------------------------------
    # Apply the parametrised ``OTLP_Endpoint_Vars`` state.
    # ------------------------------------------------------------------
    if state["traces"] is None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", state["traces"])
    if state["generic"] is None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", state["generic"])

    # Reset the idempotent guard so this invocation behaves as the **first**
    # call in a process lifetime (the only call the property quantifies over).
    monkeypatch.setattr(cce_otel, "_INITIALISED", False)

    # Property under test.
    cce_otel.init_otel()

    # ------------------------------------------------------------------
    # Assertions.
    # ------------------------------------------------------------------
    assert len(recorded) == 1, (
        f"expected exactly one exporter constructor call for state "
        f"{state['id']!r}, got {len(recorded)}: {recorded!r}"
    )
    cls, kwargs = recorded[0]

    if state["expected_kind"] == "console":
        assert cls is _SpyConsoleSpanExporter, (
            f"state {state['id']!r}: expected ConsoleSpanExporter, "
            f"got {cls.__name__}"
        )
        # Per design §"Property 3": ``out=sys.stderr`` exactly. Identity
        # comparison ensures the exporter is writing to the live
        # ``sys.stderr`` reference, not some snapshot. The ``formatter=``
        # kwarg is also passed to satisfy Requirement 2.3 (one-line JSON
        # per span); its lambda identity is intentionally not locked.
        assert kwargs.get("out") is _sys.stderr, (
            f"state {state['id']!r}: expected out=sys.stderr, "
            f"got out={kwargs.get('out')!r}"
        )
        assert "formatter" in kwargs, (
            f"state {state['id']!r}: ConsoleSpanExporter must be constructed "
            f"with an explicit formatter (Requirement 2.3 one-line-per-span); "
            f"kwargs={kwargs!r}"
        )
    elif state["expected_kind"] == "otlp":
        assert cls is _SpyOTLPSpanExporter, (
            f"state {state['id']!r}: expected OTLPSpanExporter, "
            f"got {cls.__name__}"
        )
        assert kwargs == {"endpoint": state["expected_endpoint"]}, (
            f"state {state['id']!r}: expected OTLPSpanExporter kwargs "
            f"{{'endpoint': {state['expected_endpoint']!r}}}, got {kwargs!r}"
        )
    else:  # pragma: no cover - guards against future misedits of the table
        raise AssertionError(
            f"unknown expected_kind {state['expected_kind']!r} in state {state['id']!r}"
        )


# ---------------------------------------------------------------------------
# Property 5: stdout discipline
# ---------------------------------------------------------------------------
# Feature: preqo1-span-reconciliation, Property 5: stdout discipline
# Validates: Requirements 5.1, 5.5, 5.6, 6.14.
#
# For any ``Golden_Fixtures`` entry G and any ``OTLP_Endpoint_Vars`` state S
# in ``{both unset, only TRACES set, only generic set, both set}``, the bytes
# captured from ``Score_CLI``'s ``sys.stdout`` for a successful run MUST
# match the regex ``^sha256:[0-9a-f]{64}\n$`` exactly, with total captured
# stdout length 72 bytes (7 ASCII for ``sha256:``, 64 ASCII for the hex
# digest, 1 ASCII for the trailing newline).
#
# This guards two failure modes (per design §"Property 5"):
#
#   * A future ``print(...)`` call accidentally targeting ``sys.stdout``
#     instead of ``sys.stderr`` (a regression would fail the regex match).
#   * An exporter being misconfigured to write JSON-line spans to
#     ``sys.stdout`` (a regression would push captured length above 72).
#
# Implementation strategy:
#
# 1. Copy ``tests/fixtures/simple_python`` into a per-test ``tmp_path``
#    subdirectory and deterministically ``git init`` it with the
#    ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` env vars from
#    ``docs/reproductions/README.md``. This avoids depending on the
#    outer repository's ``.git`` directory and matches the existing
#    pattern in ``tests/test_submodule_trap.py``.
#
# 2. For each of the four OTLP states, configure the ``OTEL_EXPORTER_OTLP_*``
#    environment variables on the ``cce score`` subprocess. For "set"
#    states, point the endpoint variable at the in-process stub OTLP
#    collector helper from ``tests/test_otel_collector_stub.py``
#    (kernel-assigned port on ``127.0.0.1``); the stub accepts the OTLP
#    HTTP payload, returns 200, and the BatchSpanProcessor flushes
#    cleanly on subprocess shutdown.
#
# 3. Invoke ``uv run cce score --spec ./scoring-spec.yaml --repo <tmp> \
#    --mode repo --out <tmp_out>`` via ``subprocess.run`` with
#    ``capture_output=True``. ``capture_output=True`` separates stdout
#    and stderr into independent buffers, which is exactly what
#    Requirement 5.5 / 5.6 quantify over.
#
# 4. Assert (a) ``proc.returncode == 0``, (b) captured stdout matches
#    ``^sha256:[0-9a-f]{64}\n$`` exactly with length 72, and (c) no line
#    of captured stdout parses as a JSON object with a string ``name``
#    field matching ``^cce\.[a-z_]+$`` — the latter check using the same
#    ``_extract_span_names`` helper Property 4 already exercises against
#    the Span_Gate parser contract.
#
# The four-state OTLP matrix is a finite, four-element input space;
# ``pytest.parametrize`` is the right tool. Hypothesis would only add
# cost without expanding coverage.

import os
import shutil
import subprocess
import sys

# Anchor every subprocess at the repository root so ``./scoring-spec.yaml``
# (a path relative to the cwd, per the task's verbatim subprocess
# signature) resolves correctly under ``pytest`` invocations from any
# subdirectory. ``_REPO_ROOT`` is already defined at module top.

# Match the regex exactly — Requirement 5.1's literal regex, byte-for-byte.
_RECORD_HASH_LINE_RE = re.compile(rb"^sha256:[0-9a-f]{64}\n$")

# Total bytes in a well-formed record_hash line: 7 ('sha256:') + 64 (hex) + 1 ('\n').
_RECORD_HASH_LINE_LEN = 72


def _git_init_simple_python_fixture(work: Path) -> None:
    """Copy ``tests/fixtures/simple_python`` into ``work`` and git-init it.

    Uses the deterministic ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` env vars
    documented in ``docs/reproductions/README.md`` and exercised by the
    existing ``tests/test_submodule_trap.py`` helper. The resulting
    repository's ``HEAD`` sha is reproducible across runs, which keeps
    Property 5 hermetic — a non-deterministic ``HEAD`` would leak into
    the ``cce score`` output and Property 5 would still pass (it
    quantifies only over the regex shape) but the subprocess would lose
    the byte-for-byte determinism the design relies on.

    The materialisation step (copy committed sources while EXCLUDING
    ``expected_record_hash.txt`` and any pre-existing ``.git``) mirrors
    ``scripts/regenerate_expected_record_hashes.py::_materialise_fixture``
    byte-for-byte. Property 5 does not assert against
    ``expected_record_hash.txt``, but using the canonical procedure here
    keeps every fixture-init helper in this module byte-equivalent so
    accidental drift between Property 2 and Property 5 cells is
    impossible.
    """
    src = _FIXTURES_ROOT / "simple_python"
    assert src.is_dir(), f"missing committed fixture: {src}"
    # Mirror ``_materialise_fixture`` in
    # ``scripts/regenerate_expected_record_hashes.py``: iterate the
    # committed source tree and copy each entry into ``work`` while
    # skipping ``expected_record_hash.txt`` and ``.git``. The committed
    # fixture has no ``.git`` directory today, but the exclusion is kept
    # to match the canonical procedure so any future addition cannot
    # silently drift the resulting HEAD sha.
    work.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name in {"expected_record_hash.txt", ".git"}:
            continue
        target = work / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
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
        [
            "git",
            "-c", "user.email=cce@example.test",
            "-c", "user.name=CCE Test",
            "add",
            ".",
        ],
        cwd=work,
        check=True,
        env=env,
    )
    subprocess.run(
        [
            "git",
            "-c", "user.email=cce@example.test",
            "-c", "user.name=CCE Test",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=work,
        check=True,
        env=env,
    )


def _captured_stdout_contains_no_json_span_line(stdout_bytes: bytes) -> bool:
    """``True`` iff captured stdout has no JSON-line span output.

    A "JSON-line span" is any ``\\n``-delimited line that the Span_Gate
    parser (``_extract_span_names``, exercised by Property 4) would
    accept — i.e. a line that parses as a JSON object with a string
    ``name`` field matching ``^cce\\.[a-z_]+$``. Requirement 5.6
    forbids any such line on stdout regardless of exporter selection.

    Decoding stdout as UTF-8 with ``errors="replace"`` is intentional:
    the legitimate stdout content (``record_hash`` line) is pure ASCII,
    so any decode replacement would itself indicate a regression worth
    surfacing, but we do not want a stray non-UTF-8 byte to mask the
    JSON-line check by raising ``UnicodeDecodeError``.
    """
    text = stdout_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return _extract_span_names(lines) == set()


_PROPERTY_5_OTLP_STATES: tuple[str, ...] = (
    "both_unset",
    "only_traces_set",
    "only_generic_set",
    "both_set",
)


@pytest.mark.parametrize("otlp_state", _PROPERTY_5_OTLP_STATES)
def test_property_5_stdout_discipline(
    otlp_state: str,
    tmp_path: Path,
) -> None:
    """``cce score`` writes exactly the ``record_hash`` line to stdout.

    Validates: Requirements 5.1, 5.5, 5.6, 6.14.

    Parametrised over the four-state OTLP endpoint matrix
    ``{both unset, only TRACES set, only generic set, both set}`` ×
    the ``simple_python`` Golden_Fixtures entry. For OTLP-set states the
    endpoint variable points at the in-process stub OTLP collector from
    ``tests/test_otel_collector_stub.py`` (kernel-assigned port on
    ``127.0.0.1``) so the OTLPSpanExporter has a real receiver to flush
    against on subprocess shutdown.
    """
    # Lazy import so the module remains importable on environments where
    # the stub collector helper has not yet landed (it is committed by
    # task 3.4 of this same spec).
    from tests.test_otel_collector_stub import start_collector

    # Hermetic fixture: copy + deterministic git-init so ``cce score
    # --mode repo`` resolves a reproducible ``HEAD`` independent of the
    # outer repository's ``.git`` directory.
    repo_path = tmp_path / "simple_python"
    _git_init_simple_python_fixture(repo_path)
    out_dir = tmp_path / "cce-out"

    # Build the subprocess environment. ``os.environ`` is the base so
    # PATH / HOME / locale propagate; only the OTLP endpoint variables
    # are state-dependent. Both variables are explicitly assigned (or
    # cleared) per ``otlp_state`` so the test does not silently inherit
    # whatever the developer's shell happens to export.
    base_env = {**os.environ}
    base_env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    base_env.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)

    # ``with`` context: the stub collector is only spun up for OTLP
    # states. A ``contextlib.ExitStack``-shaped indirection would also
    # work but the four-state if/elif chain is clearer at this size.
    if otlp_state == "both_unset":
        # ConsoleSpanExporter branch — the dev image's default.
        proc = subprocess.run(
            [
                "uv", "run", "cce", "score",
                "--spec", "./scoring-spec.yaml",
                "--repo", str(repo_path),
                "--mode", "repo",
                "--out", str(out_dir),
            ],
            cwd=str(_REPO_ROOT),
            env=base_env,
            capture_output=True,
            timeout=120,
        )
    else:
        with start_collector() as collector:
            endpoint_url = collector.endpoint_url
            env = dict(base_env)
            if otlp_state == "only_traces_set":
                env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = endpoint_url
            elif otlp_state == "only_generic_set":
                # The OTLPSpanExporter appends ``/v1/traces`` to the
                # generic endpoint by default. Strip the suffix so the
                # exporter rebuilds the same URL the stub listens on.
                generic_url = endpoint_url[: -len("/v1/traces")] if endpoint_url.endswith(
                    "/v1/traces"
                ) else endpoint_url
                env["OTEL_EXPORTER_OTLP_ENDPOINT"] = generic_url
            elif otlp_state == "both_set":
                # Per the design §"Property 3" precedence rule, TRACES
                # wins when both are set. Both variables are pointed at
                # the same stub so a regression that flips precedence
                # (generic wins) would still hit a live receiver and
                # cce score would still exit 0 — which is what Property 5
                # quantifies over. The precedence contract itself is
                # exercised by Property 3 (above).
                env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = endpoint_url
                env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint_url
            else:  # pragma: no cover - guards against future misedits
                raise AssertionError(f"unknown otlp_state {otlp_state!r}")

            proc = subprocess.run(
                [
                    "uv", "run", "cce", "score",
                    "--spec", "./scoring-spec.yaml",
                    "--repo", str(repo_path),
                    "--mode", "repo",
                    "--out", str(out_dir),
                ],
                cwd=str(_REPO_ROOT),
                env=env,
                capture_output=True,
                timeout=120,
            )

    # ------------------------------------------------------------------
    # Assertions.
    # ------------------------------------------------------------------
    # (a) cce score exited cleanly. We surface stderr in the failure
    # message because subprocess.run's default repr does not include it,
    # and Requirement 5.7's diagnostics are only useful if a reviewer
    # can see them in the failure output.
    assert proc.returncode == 0, (
        f"cce score exited {proc.returncode} for otlp_state={otlp_state!r}\n"
        f"--- stderr ---\n{proc.stderr.decode('utf-8', errors='replace')}\n"
        f"--- stdout ---\n{proc.stdout.decode('utf-8', errors='replace')}"
    )

    # (b) Captured stdout matches the record_hash regex exactly with
    # total length 72 bytes — Requirement 5.1 / 5.5. The byte-length
    # check is redundant with the regex (the regex's character classes
    # pin every byte) but kept as an explicit assertion so a regression
    # that produced extra bytes BEFORE the record_hash line would
    # surface as "length 144" rather than as a less-helpful regex miss.
    assert len(proc.stdout) == _RECORD_HASH_LINE_LEN, (
        f"captured stdout length is {len(proc.stdout)}, expected "
        f"{_RECORD_HASH_LINE_LEN} for otlp_state={otlp_state!r}\n"
        f"stdout bytes: {proc.stdout!r}"
    )
    assert _RECORD_HASH_LINE_RE.fullmatch(proc.stdout), (
        f"captured stdout does not match ^sha256:[0-9a-f]{{64}}\\n$ "
        f"for otlp_state={otlp_state!r}\nstdout bytes: {proc.stdout!r}"
    )

    # (c) No JSON-line span output appears on stdout regardless of
    # endpoint state — Requirement 5.6. This guards specifically against
    # an exporter being misconfigured to write to sys.stdout (e.g. a
    # future ConsoleSpanExporter() default-out regression).
    assert _captured_stdout_contains_no_json_span_line(proc.stdout), (
        f"captured stdout contains a JSON-line span output for "
        f"otlp_state={otlp_state!r}; stdout bytes: {proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Property 2 (full form): record_hash invariance under exporter choice and SDK presence
# ---------------------------------------------------------------------------
# Feature: preqo1-span-reconciliation, Property 2 (full form): record_hash invariance under exporter choice and SDK presence  # noqa: E501
# Validates: Requirements 6.1, 6.3, 3.8.
#
# For any ``Golden_Fixtures`` entry G in
# ``{simple_python, simple_typescript, perf_100k}`` and any
# ``OTLP_Endpoint_Vars`` state S in
# ``{both unset, only TRACES set, only generic set, both set}`` and any
# SDK presence P in ``{SDK installed, SDK absent → NoopTracer}``, the
# ``record_hash`` printed to stdout by ``cce score`` against G MUST equal
# the bytes of ``tests/fixtures/<G>/expected_record_hash.txt`` (modulo the
# single trailing-``\n`` rule of Requirement 6.1).
#
# This is the central non-regression invariant of the spec: instrumentation
# selection (which exporter is wired up, whether the SDK is even imported)
# cannot influence the deterministic byte output of ``Score_CLI``. The
# cross product is ``|G| × |S| × |P| = 3 × 4 × 2 = 24`` cells.
#
# Coverage allocation:
#
#   * ``simple_python`` and ``simple_typescript`` cells (4 OTLP × 2 SDK ×
#     2 fixtures = 16 cells) run by default. The fixtures are small and
#     each subprocess takes a few seconds.
#   * ``perf_100k`` cells (4 OTLP × 2 SDK = 8 cells) are gated behind the
#     ``CCE_RUN_PERF=1`` env var (matching the gate already used by
#     ``tests/perf/test_100k_loc.py``). The perf fixture costs ~30s per
#     subprocess and the ``record_hash`` invariance claim is genuinely
#     covered for that fixture by the existing ``Frozen_Hash_Gate`` in
#     ``.github/workflows/poc-determinism.yml`` (which runs the
#     ``(perf_100k, both unset, SDK installed)`` cell on every push) plus
#     the smaller fixtures' cells (which are byte-equivalent under the
#     same code path). Operators MAY run the full perf cells locally with
#     ``CCE_RUN_PERF=1 uv run pytest tests/test_otel_properties.py``.
#
# Note: the existing ``Frozen_Hash_Gate`` in
# ``.github/workflows/poc-determinism.yml`` (added by the prior spec
# ``poc-readiness-hard-blockers``) already enforces every
# ``(G, both unset, SDK installed)`` cell on every push; this property
# extends coverage to the remaining 21 cells.
#
# Implementation strategy:
#
# 1. ``_git_init_property_2_fixture`` is a per-fixture helper that
#    materialises ``tests/fixtures/<G>`` into a tmpdir and ``git init``-s
#    it deterministically, matching the protocol in
#    ``docs/reproductions/README.md`` byte-for-byte (same env vars as
#    ``test_span_names._git_init_fixture_copy`` and
#    ``test_otel_properties._git_init_simple_python_fixture``). The
#    ``perf_100k`` fixture is a generator rather than committed source,
#    so the helper invokes ``build_fixture(work / "repo")`` and returns
#    the inner ``repo/`` directory as the actual fixture root.
#
# 2. For OTLP-set states (3 of 4), the test spawns the
#    ``StubOtlpCollector`` from ``tests/test_otel_collector_stub.py`` on
#    a kernel-assigned ``127.0.0.1`` port and passes its endpoint URL
#    through the appropriate env var.
#
# 3. For the ``SDK absent`` cell of P, the test invokes ``cce score`` via
#    a small wrapper script written into the tmpdir. The script installs
#    a ``meta_path`` finder that raises ``ImportError`` for any
#    ``opentelemetry`` or ``opentelemetry.*`` import attempt BEFORE
#    importing ``cce.cli``, then calls ``cce.cli.main(...)``. Because all
#    SDK imports inside ``src/cce/otel.py`` are wrapped in soft-import
#    blocks, the meta_path finder forces the ``_NoopTracer`` fallback
#    branch (Requirement 3.8) end-to-end through the subprocess, with
#    no shared state between the parent test process and the child.
#
# 4. For each cell the test asserts (a) ``proc.returncode == 0``,
#    (b) captured stdout's bytes equal the bytes of the fixture's
#    ``expected_record_hash.txt`` after stripping at most one trailing
#    ``\n`` from each side (the comparison rule fixed by
#    Requirement 6.1).

# Match Requirement 6.1's exact comparison rule: strip at most one trailing
# ``\n`` from BOTH sides before comparing. This is the only normalisation
# applied — Requirement 6.1 is explicit that no other normalisation is in
# scope. ``cce score``'s stdout writes the hash via ``print(...)`` which
# always appends one ``\n``; the committed ``expected_record_hash.txt``
# files also end in exactly one ``\n``; both sides ending in ``\n`` is the
# documented happy path, but a regression that drops the trailing newline
# on one side would still fail the byte-equality assertion below.
def _strip_one_trailing_newline(data: bytes) -> bytes:
    """Strip at most one trailing ``\\n`` byte (Requirement 6.1 rule)."""
    if data.endswith(b"\n"):
        return data[:-1]
    return data


# Deterministic git env shared by every cell. Identical content to the
# protocol in ``docs/reproductions/README.md`` and to the existing helpers
# ``_git_init_simple_python_fixture`` / ``_git_init_fixture_copy``. Lifted
# to a module-level constant to keep the four call sites byte-equal.
_DETERMINISTIC_GIT_ENV: dict[str, str] = {
    "GIT_AUTHOR_NAME": "CCE Test",
    "GIT_AUTHOR_EMAIL": "cce@example.test",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "CCE Test",
    "GIT_COMMITTER_EMAIL": "cce@example.test",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
}


def _git_init_property_2_fixture(fixture_name: str, work: Path) -> Path:
    """Materialise ``Golden_Fixtures[fixture_name]`` into ``work`` and git-init.

    Returns the actual repo root for ``cce score`` to consume:

    * For committed fixtures (``simple_python``, ``simple_typescript``)
      the source tree is copied into ``work`` directly and ``work``
      itself is the repo root.
    * For ``perf_100k`` (a generator rather than committed source), the
      ~100 000 LoC fixture is built into ``work / "repo"`` via
      :func:`tests.fixtures.perf_100k.generate.build_fixture` and that
      ``repo/`` directory is returned as the repo root, matching the
      ``Frozen_Hash_Gate`` "Resolve fixture root" step in
      ``.github/workflows/poc-determinism.yml``.

    The deterministic git env vars exactly match
    ``docs/reproductions/README.md`` so the resulting ``HEAD`` sha
    (and therefore the ``record_hash``) is reproducible across runs.
    """
    if fixture_name == "perf_100k":
        # Lazy import: the perf fixture is regenerated on demand so the
        # repo stays small. Importing eagerly would couple this property
        # test's import-time cost to the generator's import-time cost
        # (currently negligible, but the indirection is documented).
        from tests.fixtures.perf_100k.generate import build_fixture

        repo_root = work / "repo"
        build_fixture(repo_root)
    else:
        src = _FIXTURES_ROOT / fixture_name
        assert src.is_dir(), f"missing committed fixture: {src}"
        # Mirror ``_materialise_fixture`` in
        # ``scripts/regenerate_expected_record_hashes.py``: iterate the
        # committed source tree and copy each entry into ``work`` while
        # skipping ``expected_record_hash.txt`` and ``.git``. This is
        # the binding procedure that produced every committed
        # ``expected_record_hash.txt`` — copying ``expected_record_hash.txt``
        # itself into the test repo would change the resulting tree
        # (and therefore the ``HEAD`` sha and ``record_hash``) so the
        # exclusion is load-bearing for Property 2's assertion.
        work.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            if entry.name in {"expected_record_hash.txt", ".git"}:
                continue
            target = work / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, target)
        repo_root = work

    env = {**os.environ, **_DETERMINISTIC_GIT_ENV}
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main"],
        cwd=repo_root,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.email", "cce@example.test"],
        cwd=repo_root,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "CCE Test"],
        cwd=repo_root,
        check=True,
        env=env,
    )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"],
        cwd=repo_root,
        check=True,
        env=env,
    )
    return repo_root


# Wrapper script body invoked by the SDK-absent cells. The script installs
# a ``meta_path`` finder that blocks every ``opentelemetry`` or
# ``opentelemetry.*`` import attempt BEFORE importing ``cce.cli``, then
# delegates to ``cce.cli.main(sys.argv[1:])``. The finder logic is
# byte-identical (modulo formatting) to ``_OpentelemetryBlockingFinder``
# in ``tests/test_otel.py``, lifted into a fresh subprocess so the
# blocking is hermetic — the parent test process keeps its real SDK
# install untouched.
#
# The exit code from ``cce.cli.main(...)`` is propagated as the script's
# exit code, so ``subprocess.run(...).returncode`` reflects exactly what
# ``cce score`` would have returned without the wrapper. The script is
# written into the test's ``tmp_path`` once per cell rather than committed
# to the repo so a future change to the wrapper does not require touching
# fixture data.
_SDK_ABSENT_WRAPPER_SCRIPT = '''\
"""SDK-absent wrapper: block every ``opentelemetry*`` import then run cce.cli.main.

This script is generated at test time by Property 2 (full form) in
``tests/test_otel_properties.py``. It exists to simulate Requirement 3.8
(``record_hash`` invariance when the OpenTelemetry SDK is absent) inside
a fresh subprocess so the blocking is hermetic — the parent pytest
process keeps its real SDK install untouched.
"""
from __future__ import annotations

import sys


class _OpentelemetryBlockingFinder:
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
            raise ImportError(f"blocked by SDK-absent wrapper: {fullname}")
        return None


# Drop any cached opentelemetry modules so subsequent imports resolve via
# meta_path (and hit the blocking finder above). The dev image installs
# the SDK by default; without this loop the soft-import block inside
# init_otel could resolve from sys.modules before the meta_path lookup.
_otel_cached = [
    _n for _n in list(sys.modules)
    if _n == "opentelemetry" or _n.startswith("opentelemetry.")
]
for _name in _otel_cached:
    del sys.modules[_name]

# Insert the blocking finder at the head of sys.meta_path BEFORE importing
# cce.cli. cce.cli does not itself import opentelemetry at module load
# (every SDK reference lives inside cce.otel.init_otel), so this ordering
# is sufficient.
sys.meta_path.insert(0, _OpentelemetryBlockingFinder)

from cce.cli import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
'''


def _run_cce_score_property_2(
    repo_root: Path,
    out_dir: Path,
    *,
    sdk_state: str,
    env: dict[str, str],
    timeout: int,
    tmp_path: Path,
) -> subprocess.CompletedProcess[bytes]:
    """Invoke ``cce score`` for one Property 2 cell.

    Dispatches between the SDK-installed and SDK-absent code paths:

    * ``sdk_installed``: standard ``python -m cce score ...`` invocation
      (matching the pattern used by ``test_console_exporter_emits_json_lines_to_stderr``).
    * ``sdk_absent``: writes the SDK-absent wrapper script into
      ``tmp_path`` and runs it with the same arguments. The wrapper
      blocks every ``opentelemetry*`` import via ``meta_path`` BEFORE
      importing ``cce.cli``, forcing the ``_NoopTracer`` fallback path.

    The two code paths share ``argv``, ``env``, ``cwd``, and ``timeout``
    so the only observable difference between cells is the import
    blocking. Output is captured as raw bytes (not text) so the
    ``record_hash`` byte-equality assertion is byte-exact.
    """
    argv = [
        "score",
        "--spec",
        str(_REPO_ROOT / "scoring-spec.yaml"),
        "--repo",
        str(repo_root),
        "--mode",
        "repo",
        "--out",
        str(out_dir),
    ]

    if sdk_state == "sdk_installed":
        cmd = [sys.executable, "-m", "cce", *argv]
    elif sdk_state == "sdk_absent":
        wrapper_path = tmp_path / "sdk_absent_wrapper.py"
        wrapper_path.write_text(_SDK_ABSENT_WRAPPER_SCRIPT, encoding="utf-8")
        cmd = [sys.executable, str(wrapper_path), *argv]
    else:  # pragma: no cover - guards against future misedits
        raise AssertionError(f"unknown sdk_state {sdk_state!r}")

    # ``PYTHONPATH`` lets ``python -m cce`` (and the SDK-absent wrapper's
    # ``from cce.cli import main``) resolve the package without depending
    # on ``uv run`` being on PATH inside the test environment. Identical
    # to the convention used by ``test_console_exporter_emits_json_lines_to_stderr``.
    env_for_proc = dict(env)
    env_for_proc.setdefault("PYTHONPATH", str(_REPO_ROOT / "src"))

    return subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=env_for_proc,
        capture_output=True,
        timeout=timeout,
    )


# Fixture / OTLP / SDK matrix. ``simple_python`` and ``simple_typescript``
# are tested across the full 4×2 sub-matrix; ``perf_100k`` is gated behind
# ``CCE_RUN_PERF=1`` (same gate as ``tests/perf/test_100k_loc.py``).
_PROPERTY_2_OTLP_STATES: tuple[str, ...] = (
    "both_unset",
    "only_traces_set",
    "only_generic_set",
    "both_set",
)
_PROPERTY_2_SDK_STATES: tuple[str, ...] = (
    "sdk_installed",
    "sdk_absent",
)
_PROPERTY_2_FAST_FIXTURES: tuple[str, ...] = (
    "simple_python",
    "simple_typescript",
)


def _property_2_cells(
    fixtures: tuple[str, ...],
) -> list[tuple[str, str, str]]:
    """Cartesian product of (fixture, otlp_state, sdk_state)."""
    cells: list[tuple[str, str, str]] = []
    for fixture in fixtures:
        for otlp_state in _PROPERTY_2_OTLP_STATES:
            for sdk_state in _PROPERTY_2_SDK_STATES:
                cells.append((fixture, otlp_state, sdk_state))
    return cells


def _build_property_2_env(
    *,
    otlp_state: str,
    endpoint_url: str | None,
) -> dict[str, str]:
    """Compose the subprocess env for a given OTLP state.

    Both ``OTEL_EXPORTER_OTLP_*`` variables are explicitly assigned (or
    cleared) per ``otlp_state`` so the test does not silently inherit
    whatever the developer's shell happens to export. ``endpoint_url`` is
    the stub OTLP collector URL (kernel-assigned port on
    ``127.0.0.1``) and is required for every OTLP-set state.
    """
    env = {**os.environ}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    env.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)

    if otlp_state == "both_unset":
        return env

    assert endpoint_url is not None, (
        f"otlp_state={otlp_state!r} requires endpoint_url to be set"
    )
    if otlp_state == "only_traces_set":
        env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = endpoint_url
    elif otlp_state == "only_generic_set":
        # The OTLPSpanExporter appends ``/v1/traces`` to the generic
        # endpoint by default. Strip the suffix so the exporter rebuilds
        # the same URL the stub listens on. Same convention as
        # Property 5's ``only_generic_set`` cell above.
        generic_url = endpoint_url[: -len("/v1/traces")] if endpoint_url.endswith(
            "/v1/traces"
        ) else endpoint_url
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = generic_url
    elif otlp_state == "both_set":
        # Per Property 3 precedence rule, TRACES wins when both are
        # set. Pointing both at the same stub keeps Property 2's
        # invariance assertion robust to a regression that flipped
        # precedence (the regression would still hit a live receiver).
        env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = endpoint_url
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint_url
    else:  # pragma: no cover - guards against future misedits
        raise AssertionError(f"unknown otlp_state {otlp_state!r}")
    return env


def _assert_property_2_record_hash(
    fixture_name: str,
    proc: subprocess.CompletedProcess[bytes],
    cell_id: str,
) -> None:
    """Assert ``proc`` exited 0 and wrote the expected ``record_hash`` to stdout.

    The byte-equality comparison applies the single-trailing-``\\n`` rule
    of Requirement 6.1: strip at most one trailing ``\\n`` from BOTH the
    captured stdout and the committed ``expected_record_hash.txt`` bytes
    before comparing. No other normalisation is applied.
    """
    expected_path = _FIXTURES_ROOT / fixture_name / "expected_record_hash.txt"
    expected_bytes = expected_path.read_bytes()

    assert proc.returncode == 0, (
        f"cce score exited {proc.returncode} for cell {cell_id!r}\n"
        f"--- stderr ---\n{proc.stderr.decode('utf-8', errors='replace')}\n"
        f"--- stdout ---\n{proc.stdout.decode('utf-8', errors='replace')}"
    )

    observed = _strip_one_trailing_newline(proc.stdout)
    expected = _strip_one_trailing_newline(expected_bytes)
    assert observed == expected, (
        f"record_hash drift for cell {cell_id!r}\n"
        f"  fixture  = {fixture_name!r}\n"
        f"  expected = {expected!r}\n"
        f"  observed = {observed!r}\n"
        f"  full stdout = {proc.stdout!r}\n"
        f"  stderr      = {proc.stderr.decode('utf-8', errors='replace')}"
    )


@pytest.mark.parametrize(
    ("fixture_name", "otlp_state", "sdk_state"),
    _property_2_cells(_PROPERTY_2_FAST_FIXTURES),
    ids=lambda v: v,
)
def test_property_2_record_hash_invariance_fast(
    fixture_name: str,
    otlp_state: str,
    sdk_state: str,
    tmp_path: Path,
) -> None:
    """``record_hash`` is byte-equal to ``expected_record_hash.txt`` for every
    ``(fast fixture, OTLP state, SDK state)`` cell.

    Validates: Requirements 6.1, 6.3, 3.8.

    Covers 16 of the 24 cells in the full Property 2 matrix
    (``simple_python`` and ``simple_typescript`` × 4 OTLP states × 2 SDK
    states). The remaining 8 cells (``perf_100k``) are exercised by
    ``test_property_2_record_hash_invariance_perf`` below, gated behind
    ``CCE_RUN_PERF=1``.
    """
    if sdk_state == "sdk_installed":
        # The SDK-installed cells genuinely need the SDK importable; if
        # it is not, the run silently falls back to ``_NoopTracer`` and
        # the test would still pass (record_hash is invariant under that
        # fallback) but the parametrisation would no longer exercise the
        # OTLP / Console exporter branches. Skipping is the right
        # response — Requirement 3.8 ``SDK absent`` cell is exercised by
        # the ``sdk_absent`` parametrisation below.
        pytest.importorskip("opentelemetry.sdk.trace.export")
        pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    cell_id = f"{fixture_name}|{otlp_state}|{sdk_state}"

    repo_root = _git_init_property_2_fixture(fixture_name, tmp_path / "repo")
    out_dir = tmp_path / "cce-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if otlp_state == "both_unset":
        env = _build_property_2_env(otlp_state=otlp_state, endpoint_url=None)
        proc = _run_cce_score_property_2(
            repo_root,
            out_dir,
            sdk_state=sdk_state,
            env=env,
            timeout=180,
            tmp_path=tmp_path,
        )
    else:
        # Lazy import keeps this module importable on hosts where the
        # stub helper has not yet landed (it is committed by task 3.4).
        from tests.test_otel_collector_stub import start_collector

        with start_collector() as collector:
            env = _build_property_2_env(
                otlp_state=otlp_state, endpoint_url=collector.endpoint_url
            )
            proc = _run_cce_score_property_2(
                repo_root,
                out_dir,
                sdk_state=sdk_state,
                env=env,
                timeout=180,
                tmp_path=tmp_path,
            )

    _assert_property_2_record_hash(fixture_name, proc, cell_id)


@pytest.mark.skipif(
    os.environ.get("CCE_RUN_PERF") != "1",
    reason="set CCE_RUN_PERF=1 to enable perf_100k cells of Property 2 (full form)",
)
@pytest.mark.parametrize(
    ("otlp_state", "sdk_state"),
    [
        (otlp_state, sdk_state)
        for otlp_state in _PROPERTY_2_OTLP_STATES
        for sdk_state in _PROPERTY_2_SDK_STATES
    ],
    ids=lambda v: v,
)
def test_property_2_record_hash_invariance_perf(
    otlp_state: str,
    sdk_state: str,
    tmp_path: Path,
) -> None:
    """``record_hash`` is byte-equal to ``expected_record_hash.txt`` for every
    ``(perf_100k, OTLP state, SDK state)`` cell.

    Validates: Requirements 6.1, 6.3, 3.8.

    Covers the remaining 8 cells of the full Property 2 matrix that the
    "fast" test above leaves out. Gated behind ``CCE_RUN_PERF=1`` (same
    gate as ``tests/perf/test_100k_loc.py``) so the regular test suite
    does not pay the ~30s/cell cost. Operators MAY run the full perf
    cells locally with ``CCE_RUN_PERF=1 uv run pytest tests/test_otel_properties.py``.
    """
    if sdk_state == "sdk_installed":
        pytest.importorskip("opentelemetry.sdk.trace.export")
        pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    fixture_name = "perf_100k"
    cell_id = f"{fixture_name}|{otlp_state}|{sdk_state}"

    repo_root = _git_init_property_2_fixture(fixture_name, tmp_path / "repo")
    out_dir = tmp_path / "cce-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if otlp_state == "both_unset":
        env = _build_property_2_env(otlp_state=otlp_state, endpoint_url=None)
        proc = _run_cce_score_property_2(
            repo_root,
            out_dir,
            sdk_state=sdk_state,
            env=env,
            # perf_100k typically scores in under 60s in CI; allow more
            # headroom locally.
            timeout=300,
            tmp_path=tmp_path,
        )
    else:
        from tests.test_otel_collector_stub import start_collector

        with start_collector() as collector:
            env = _build_property_2_env(
                otlp_state=otlp_state, endpoint_url=collector.endpoint_url
            )
            proc = _run_cce_score_property_2(
                repo_root,
                out_dir,
                sdk_state=sdk_state,
                env=env,
                timeout=300,
                tmp_path=tmp_path,
            )

    _assert_property_2_record_hash(fixture_name, proc, cell_id)
