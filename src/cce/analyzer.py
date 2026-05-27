"""Repo-walker + dispatcher over :mod:`cce.analyzers`.

This module preserves the historical ``analyse_repo`` public API used by
``cce.cli``. The per-file metric computation is delegated to a pluggable
``AnalyzerRegistry`` so production images can swap in digest-pinned
``lizard``/``scc`` backends (PREQ-A-1) without changing call sites.

For PREQ-O-1 span reconciliation, ``analyse_repo`` is split into two
helpers ``parse_repo`` (I/O: walk + read + backend resolution + digest
verification) and ``measure_metrics`` (pure: run each backend and
aggregate). ``analyse_repo`` is preserved as a thin compatibility
wrapper so callers and ``tests/test_analyzer.py`` are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cce.analyzers import builtin, get_registry
from cce.analyzers.builtin import AnalyzerError
from cce.analyzers.registry import AnalyzerRegistry
from cce.spec import METRIC_NAMES


def _analyse_python(text: str) -> dict[str, int]:
    """Compatibility shim for legacy callers/tests (pre-registry API)."""
    return builtin.analyse_python(Path("<inline>"), text)


def _analyse_typescript(text: str) -> dict[str, int]:
    """Compatibility shim for legacy callers/tests (pre-registry API)."""
    return builtin.analyse_typescript(Path("<inline>"), text)


_SOURCE_SUFFIXES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__", "cce-out"}


@dataclass(frozen=True)
class FileMetrics:
    path: str
    language: str
    metrics: dict[str, int]


@dataclass(frozen=True)
class _SourceFile:
    """Walked source file resolved to its analyzer entry.

    Module-private value object consumed by :func:`measure_metrics`.
    """

    relative_posix: str
    absolute_path: Path
    language: str
    text: str
    backend: Callable[[Path, str], dict[str, int]]


@dataclass(frozen=True)
class ParseContext:
    """Immutable result of the parse phase. Consumed by ``measure_metrics``.

    ``files`` is sorted lexicographically by ``relative_posix`` so the
    downstream aggregation is deterministic and byte-identical to the
    legacy single-pass ``analyse_repo`` ordering.
    """

    repo_path: Path
    files: tuple[_SourceFile, ...]


def parse_repo(
    repo_path: Path,
    *,
    registry: AnalyzerRegistry | None = None,
    tool_digests: dict[str, str] | None = None,
) -> ParseContext:
    """Walk ``repo_path`` and return an immutable :class:`ParseContext`.

    Side effects (intentional, documented):
      * Reads files from disk via :meth:`pathlib.Path.read_text`.
      * If ``tool_digests`` is non-``None``, calls
        ``registry.assert_digests(tool_digests)`` exactly once BEFORE
        any file read. This preserves the single-call digest
        verification contract from :func:`analyse_repo`.

    The returned ``ParseContext.files`` tuple is sorted lexicographically
    by relative POSIX path, matching the previous ``analyse_repo``
    ordering byte-for-byte.
    """
    registry = registry or get_registry()
    if tool_digests is not None:
        registry.assert_digests(tool_digests)

    entries: list[_SourceFile] = []
    for path in _iter_source_files(repo_path):
        relative = path.relative_to(repo_path).as_posix()
        language = _SOURCE_SUFFIXES[path.suffix]
        backend = registry.resolve(language).backend
        text = path.read_text(encoding="utf-8", errors="replace")
        entries.append(
            _SourceFile(
                relative_posix=relative,
                absolute_path=path,
                language=language,
                text=text,
                backend=backend,
            )
        )

    return ParseContext(repo_path=repo_path, files=tuple(entries))


def measure_metrics(
    ctx: ParseContext,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Run each file's backend and aggregate the summary.

    Pure function of ``ctx``: no I/O, no time, no environment access.
    The output is byte-identical to ``analyse_repo``'s previous output
    for any ``ctx`` produced by :func:`parse_repo` against the same
    ``repo_path``.
    """
    files: list[FileMetrics] = []
    for source in ctx.files:
        metrics = source.backend(source.absolute_path, source.text)
        metrics["file_length"] = len(source.text.splitlines())
        files.append(
            FileMetrics(
                path=source.relative_posix,
                language=source.language,
                metrics=metrics,
            )
        )

    summary = {metric: 0 for metric in METRIC_NAMES}
    for file_metrics in files:
        for metric in METRIC_NAMES:
            summary[metric] = max(summary[metric], file_metrics.metrics[metric])

    raw_metrics = {metric: str(summary[metric]) for metric in METRIC_NAMES}
    raw_payload = {
        "files": [
            {
                "path": file_metrics.path,
                "language": file_metrics.language,
                "metrics": file_metrics.metrics,
            }
            for file_metrics in files
        ],
        "summary": summary,
    }
    return raw_metrics, raw_payload


def analyse_repo(
    repo_path: Path,
    *,
    registry: AnalyzerRegistry | None = None,
    tool_digests: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Walk ``repo_path`` and produce ``(raw_metrics, raw_payload)``.

    Compatibility wrapper preserved for existing callers and
    ``tests/test_analyzer.py``. Equivalent to::

        ctx = parse_repo(repo_path, registry=registry, tool_digests=tool_digests)
        return measure_metrics(ctx)

    If ``tool_digests`` is provided and the active registry has any
    digest-pinned backends, every pinned binary is verified before any
    file is analyzed (PREQ-A-1).
    """
    ctx = parse_repo(repo_path, registry=registry, tool_digests=tool_digests)
    return measure_metrics(ctx)


def _iter_source_files(repo_path: Path) -> list[Path]:
    paths: list[Path] = []
    for path in repo_path.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
            paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(repo_path).as_posix())


__all__ = [
    "AnalyzerError",
    "FileMetrics",
    "ParseContext",
    "analyse_repo",
    "measure_metrics",
    "parse_repo",
]
