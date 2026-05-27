from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cce.analyzer import AnalyzerError, measure_metrics, parse_repo
from cce.canonical import canonical_json_bytes
from cce.git_ops import GitSafetyError, GitTimeoutError, prepared_repo
from cce.otel import (
    JOB_FAILURES_TOTAL,
    RECORDS_TOTAL,
    SCORE_DURATION_SECONDS,
    init_otel,
    stage_span,
)
from cce.runtime import NetworkIsolationError, assert_network_isolated
from cce.scoring import ScoringError, build_score_record, verify_record_hash
from cce.spec import SpecValidationError, load_spec, validate_digest_shapes

EXIT_SPEC = 10
EXIT_DIGEST = 11
EXIT_GIT = 12
EXIT_ANALYZER = 13
EXIT_SCORING = 14
EXIT_WRITE = 15


def entrypoint() -> None:
    raise SystemExit(main())


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "score":
        return _score(args)
    if args.command == "verify":
        return _verify(args)
    parser.print_help(sys.stderr)
    return EXIT_SPEC


def _score(args: argparse.Namespace) -> int:
    timings: list[tuple[str, int]] = []
    total_start = time.perf_counter_ns()
    # PREQ-O-1: configure OTel exporter once per process. No-op when SDK is
    # not installed (POC dev image) — production rootfs ships the SDK.
    init_otel()

    try:
        # PREQ-O-1 / Requirement 1.1: cce.load_spec wraps the spec-load call.
        with stage_span("load_spec", spec=str(args.spec)):
            spec = _timed("cce.load_spec", timings, lambda: load_spec(Path(args.spec)))
    except SpecValidationError as exc:
        JOB_FAILURES_TOTAL.labels(reason="spec").inc()
        _print_error(exc)
        return EXIT_SPEC

    if _parse_bool(args.verify_digests):
        try:
            validate_digest_shapes(spec.tool_digests)
        except SpecValidationError as exc:
            JOB_FAILURES_TOTAL.labels(reason="digest").inc()
            _print_error(exc)
            return EXIT_DIGEST

    # PREQ-A-3: assert --network=none is in effect when the operator opts in.
    # Failure shares EXIT_GIT (12) per docs/poc-prd.md §9.3 — closest existing
    # "safety / isolation" bucket; no new exit codes are introduced.
    if args.assert_network_isolated or os.environ.get("CCE_REQUIRE_NETWORK_ISOLATED") == "1":
        try:
            assert_network_isolated()
        except NetworkIsolationError as exc:
            JOB_FAILURES_TOTAL.labels(reason="network_isolation").inc()
            _print_error(exc)
            return EXIT_GIT

    git_min_version = spec.raw.get("git_min_version") if isinstance(spec.raw, dict) else None
    git_min_version_str = git_min_version if isinstance(git_min_version, str) else None

    try:
        # PREQ-O-1 / Requirement 1.2, 1.10: rename prepared_repo -> clone.
        # The cce.clone span and timing wrap ONLY the prepared_repo setup
        # (clone + checkout work in __enter__), not the inner parse / measure
        # / score phases. This is what allows the timings list to be appended
        # in the order required by Requirement 5.3:
        #     cce.load_spec, cce.clone, cce.parse, cce.measure, cce.score, cce.total
        # If we instead nested cce.parse/measure/score inside _timed_context's
        # lifetime, cce.clone would only be appended in __exit__ after the
        # inner stages, putting it at index 4 instead of index 1.
        with ExitStack() as repo_stack:
            with stage_span("clone", repo=args.repo, mode=args.mode):
                clone_start = time.perf_counter_ns()
                repo_path, commit_sha = repo_stack.enter_context(
                    prepared_repo(
                        args.repo,
                        args.mode,
                        args.commit,
                        git_min_version=git_min_version_str,
                    )
                )
                timings.append(("cce.clone", time.perf_counter_ns() - clone_start))
            # PREQ-O-1 / Requirements 1.3, 1.4, 1.11: split analyze ->
            # parse + measure. AnalyzerError / ToolDigestMismatchError
            # handlers wrap both spans so the exception-to-exit-code
            # mapping is unchanged from the prior single-span form.
            try:
                # PREQ-O-1 / Requirement 1.3: cce.parse wraps tree-sitter
                # parse + digest verification (parse_repo calls
                # registry.assert_digests once, before any file read).
                with stage_span("parse", repo=args.repo, commit_sha=commit_sha):
                    parse_ctx = _timed(
                        "cce.parse",
                        timings,
                        lambda: parse_repo(
                            repo_path,
                            # PREQ-A-1: verify pinned analyzer binaries before
                            # each scoring run. The default registry has no
                            # digest-pinned backends in the POC dev image, so
                            # this is a no-op there; production rootfs registers
                            # lizard/scc via register_production_backends().
                            tool_digests=spec.tool_digests
                            if _parse_bool(args.verify_digests)
                            else None,
                        ),
                    )

                # PREQ-O-1 / Requirement 1.4: cce.measure wraps the pure
                # metric-aggregation phase. measure_metrics is a pure
                # function of the ParseContext — no I/O, no env access.
                with stage_span("measure", repo=args.repo, commit_sha=commit_sha):
                    raw_metrics, raw_payload = _timed(
                        "cce.measure",
                        timings,
                        lambda: measure_metrics(parse_ctx),
                    )
            except AnalyzerError as exc:
                JOB_FAILURES_TOTAL.labels(reason="analyzer").inc()
                _print_error(exc)
                return EXIT_ANALYZER
            except Exception as exc:  # ToolDigestMismatchError or backend failure
                from cce.runtime import ToolDigestMismatchError

                if isinstance(exc, ToolDigestMismatchError):
                    JOB_FAILURES_TOTAL.labels(reason="digest").inc()
                    _print_error(exc)
                    return EXIT_DIGEST
                JOB_FAILURES_TOTAL.labels(reason="unexpected").inc()
                raise

            try:
                with stage_span("score", commit_sha=commit_sha):
                    record = _timed(
                        "cce.score",
                        timings,
                        lambda: build_score_record(
                            spec=spec,
                            raw_metrics=raw_metrics,
                            repo=args.repo,
                            mode=args.mode,
                            commit_sha=commit_sha,
                            computed_at=_utc_now(),
                        ),
                    )
            except ScoringError as exc:
                JOB_FAILURES_TOTAL.labels(reason="scoring").inc()
                _print_error(exc)
                return EXIT_SCORING
    except GitSafetyError as exc:
        JOB_FAILURES_TOTAL.labels(reason="git_safety").inc()
        _print_error(exc)
        return EXIT_GIT
    except GitTimeoutError as exc:
        JOB_FAILURES_TOTAL.labels(reason="git_timeout").inc()
        _print_error(exc)
        return EXIT_GIT

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with stage_span("write_outputs", record_hash=record["record_hash"]):
        try:
            _write_outputs(out_dir, record, raw_payload)
        except OSError as exc:
            JOB_FAILURES_TOTAL.labels(reason="write_output").inc()
            _print_error(exc)
            return EXIT_WRITE
    total_ns = time.perf_counter_ns() - total_start
    timings.append(("cce.total", total_ns))
    SCORE_DURATION_SECONDS.labels(stage="total").observe(total_ns / 1e9)
    RECORDS_TOTAL.inc()
    # PREQ-O-1 / Requirement 5.3: on the happy path, the timings list MUST
    # be appended-to in stage exit order. _print_timings iterates the list
    # in insertion order, so the order asserted here is the order printed
    # to stderr. If this assertion ever trips, a span boundary refactor
    # has reintroduced the ordering bug from before task 1.6 (where
    # cce.clone landed AFTER parse/measure/score because _timed_context's
    # __exit__ appended after the inner stages). Keep this list in sync
    # with the PRD_Span_Set + cce.total in `requirements.md` Requirement 5.3.
    assert [name for name, _ in timings] == [
        "cce.load_spec",
        "cce.clone",
        "cce.parse",
        "cce.measure",
        "cce.score",
        "cce.total",
    ], f"stage timing order drift: {[name for name, _ in timings]!r}"
    _print_timings(timings)
    print(record["record_hash"])
    return 0


LEGACY_SHA256_PREFIX = "sha256:"


def _verify(args: argparse.Namespace) -> int:
    # Two entry points:
    #   `cce verify --record <path>` (legacy): recomputes record_hash from the
    #     record JSON's content and compares against record["record_hash"].
    #   `cce verify --sidecar <path>` (new):   reads the GNU-coreutils-format
    #     .sha256 sidecar (also accepts the legacy "sha256:<hex>\n" form for
    #     backwards compatibility) and validates against the neighbouring
    #     <record_hash>.json file.
    sidecar = getattr(args, "sidecar", None)
    record_arg = getattr(args, "record", None)

    if sidecar:
        return _verify_sidecar(Path(sidecar))

    if not record_arg:
        _print_error("verify requires --record <path> or --sidecar <path>")
        return EXIT_SCORING

    record_path = Path(record_arg)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _print_error(exc)
        return EXIT_SCORING

    if not isinstance(record, dict) or not verify_record_hash(record):
        _print_error("record_hash mismatch")
        return EXIT_SCORING
    return 0


def _verify_sidecar(sidecar_path: Path) -> int:
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except OSError as exc:
        _print_error(exc)
        return EXIT_SCORING

    stripped = text.strip()
    if not stripped:
        _print_error("empty sidecar file")
        return EXIT_SCORING

    if stripped.startswith(LEGACY_SHA256_PREFIX):
        # Legacy format: single line "sha256:<hex>".
        expected_hex = stripped[len(LEGACY_SHA256_PREFIX) :].strip()
        # Sidecar filename pattern: "<record_hash>.sha256".
        record_name = sidecar_path.stem  # "<record_hash>"
        target_filename = f"{record_name}.json"
    else:
        # GNU coreutils format: "<hex>  <filename>".
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            _print_error("malformed sidecar (expected '<hex>  <filename>')")
            return EXIT_SCORING
        expected_hex = parts[0]
        target_filename = parts[1].lstrip("*")  # `sha256sum -b` prefixes binary-mode files with '*'

    if len(expected_hex) != 64 or any(c not in "0123456789abcdef" for c in expected_hex.lower()):
        _print_error("sidecar digest is not a 64-char sha256 hex")
        return EXIT_SCORING

    target = sidecar_path.parent / target_filename
    try:
        record_bytes = target.read_bytes()
    except OSError as exc:
        _print_error(exc)
        return EXIT_SCORING

    actual_hex = hashlib.sha256(record_bytes).hexdigest()
    if actual_hex != expected_hex.lower():
        _print_error(f"sidecar digest mismatch: expected {expected_hex}, got {actual_hex}")
        return EXIT_SCORING

    # Also re-verify record_hash from content, mirroring `verify --record`.
    try:
        record = json.loads(record_bytes)
    except json.JSONDecodeError as exc:
        _print_error(exc)
        return EXIT_SCORING
    if not isinstance(record, dict) or not verify_record_hash(record):
        _print_error("record_hash mismatch")
        return EXIT_SCORING
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cce")
    subparsers = parser.add_subparsers(dest="command", required=True)

    score = subparsers.add_parser("score")
    score.add_argument("--spec", required=True)
    score.add_argument("--repo", required=True)
    score.add_argument("--mode", choices=["repo", "commit"], default="repo")
    score.add_argument("--commit")
    score.add_argument("--out", default="./cce-out")
    score.add_argument("--verify-digests", default="true", choices=["true", "false"])
    score.add_argument(
        "--assert-network-isolated",
        action="store_true",
        help="PREQ-A-3: refuse to run if network egress is reachable.",
    )

    verify = subparsers.add_parser("verify")
    # Either --record (legacy) or --sidecar (new) is required; argparse
    # enforces "at least one" via a custom check in `main`/`_verify` since
    # mutually-exclusive groups would forbid both forms in the same invocation.
    verify.add_argument("--record")
    verify.add_argument(
        "--sidecar",
        help="Path to a <record_hash>.sha256 sidecar (GNU coreutils or legacy format).",
    )
    return parser


def _timed[T](name: str, timings: list[tuple[str, int]], operation: Callable[[], T]) -> T:
    start = time.perf_counter_ns()
    try:
        return operation()
    finally:
        timings.append((name, time.perf_counter_ns() - start))


class _timed_context[T]:
    def __init__(
        self,
        name: str,
        timings: list[tuple[str, int]],
        factory: Callable[[], Any],
    ) -> None:
        self.name = name
        self.timings = timings
        self.factory = factory
        self.started = 0
        self.context: Any = None

    def __enter__(self) -> T:
        self.started = time.perf_counter_ns()
        self.context = self.factory()
        return self.context.__enter__()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None:
        try:
            return self.context.__exit__(exc_type, exc, traceback)
        finally:
            self.timings.append((self.name, time.perf_counter_ns() - self.started))


def _write_outputs(out_dir: Path, record: dict[str, Any], raw_payload: dict[str, Any]) -> None:
    record_hash = record["record_hash"]
    record_bytes = canonical_json_bytes(record)
    raw_bytes = canonical_json_bytes(raw_payload)

    record_path = out_dir / f"{record_hash}.json"
    raw_path = out_dir / f"{record_hash}.raw.json"
    sidecar_path = out_dir / f"{record_hash}.sha256"
    json_digest = hashlib.sha256(record_bytes).hexdigest()
    sidecar_text = f"{json_digest}  {record_hash}.json\n"

    # Atomic writes: write to a temp file, then os.replace() to target.
    # On failure, raise OSError so the caller can handle it with a clean
    # exit code instead of a traceback.
    _atomic_write(record_path, record_bytes)
    _atomic_write(raw_path, raw_bytes)
    _atomic_write_text(sidecar_path, sidecar_text)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_bool(value: str) -> bool:
    return value == "true"


def _print_timings(timings: list[tuple[str, int]]) -> None:
    for name, elapsed_ns in timings:
        elapsed_ms = elapsed_ns // 1_000_000
        print(f"{name}: {elapsed_ms} ms", file=sys.stderr)


def _print_error(error: object) -> None:
    print(f"cce: {error}", file=sys.stderr)
