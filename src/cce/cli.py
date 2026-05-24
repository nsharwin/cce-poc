from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cce.analyzer import AnalyzerError, analyse_repo
from cce.canonical import canonical_json_bytes
from cce.git_ops import GitSafetyError, prepared_repo
from cce.scoring import ScoringError, build_score_record, verify_record_hash
from cce.spec import SpecValidationError, load_spec, validate_digest_shapes

EXIT_SPEC = 10
EXIT_DIGEST = 11
EXIT_GIT = 12
EXIT_ANALYZER = 13
EXIT_SCORING = 14


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

    try:
        spec = _timed("cce.load_spec", timings, lambda: load_spec(Path(args.spec)))
    except SpecValidationError as exc:
        _print_error(exc)
        return EXIT_SPEC

    if _parse_bool(args.verify_digests):
        try:
            validate_digest_shapes(spec.tool_digests)
        except SpecValidationError as exc:
            _print_error(exc)
            return EXIT_DIGEST

    try:
        with _timed_context(
            "cce.clone",
            timings,
            lambda: prepared_repo(args.repo, args.mode, args.commit),
        ) as (
            repo_path,
            commit_sha,
        ):
            try:
                raw_metrics, raw_payload = _timed(
                    "cce.measure",
                    timings,
                    lambda: analyse_repo(repo_path),
                )
            except AnalyzerError as exc:
                _print_error(exc)
                return EXIT_ANALYZER

            try:
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
                _print_error(exc)
                return EXIT_SCORING
    except GitSafetyError as exc:
        _print_error(exc)
        return EXIT_GIT

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_outputs(out_dir, record, raw_payload)
    timings.append(("cce.total", time.perf_counter_ns() - total_start))
    _print_timings(timings)
    print(record["record_hash"])
    return 0


def _verify(args: argparse.Namespace) -> int:
    record_path = Path(args.record)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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

    verify = subparsers.add_parser("verify")
    verify.add_argument("--record", required=True)
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

    (out_dir / f"{record_hash}.json").write_bytes(record_bytes)
    (out_dir / f"{record_hash}.raw.json").write_bytes(raw_bytes)
    json_digest = hashlib.sha256(record_bytes).hexdigest()
    (out_dir / f"{record_hash}.sha256").write_text(f"sha256:{json_digest}\n", encoding="utf-8")


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
