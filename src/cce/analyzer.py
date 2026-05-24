from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cce.spec import METRIC_NAMES

_SOURCE_SUFFIXES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__", "cce-out"}
_TS_BRANCH_RE = re.compile(r"\b(if|for|while|case|catch|switch|\?|&&|\|\|)\b")


@dataclass(frozen=True)
class FileMetrics:
    path: str
    language: str
    metrics: dict[str, int]


class AnalyzerError(RuntimeError):
    pass


def analyse_repo(repo_path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    files: list[FileMetrics] = []
    for path in _iter_source_files(repo_path):
        relative = path.relative_to(repo_path).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        language = _SOURCE_SUFFIXES[path.suffix]
        metrics = _analyse_python(text) if language == "python" else _analyse_typescript(text)
        metrics["file_length"] = len(text.splitlines())
        files.append(FileMetrics(path=relative, language=language, metrics=metrics))

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


def _iter_source_files(repo_path: Path) -> list[Path]:
    paths: list[Path] = []
    for path in repo_path.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
            paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(repo_path).as_posix())


def _analyse_python(text: str) -> dict[str, int]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AnalyzerError(f"failed to parse Python source: {exc}") from exc

    visitor = _PythonMetricVisitor()
    visitor.visit(tree)
    return {
        "cyclomatic": max(visitor.cyclomatic_values, default=0),
        "cognitive": max(visitor.cognitive_values, default=0),
        "nesting_depth": visitor.max_nesting_depth,
        "function_length": max(visitor.function_lengths, default=0),
        "file_length": 0,
    }


def _analyse_typescript(text: str) -> dict[str, int]:
    lines = text.splitlines()
    branch_count = sum(len(_TS_BRANCH_RE.findall(line)) for line in lines)
    max_brace_depth = 0
    brace_depth = 0
    for line in lines:
        brace_depth += line.count("{")
        max_brace_depth = max(max_brace_depth, brace_depth)
        brace_depth -= line.count("}")
        brace_depth = max(brace_depth, 0)

    function_lengths = _typescript_function_lengths(lines)
    return {
        "cyclomatic": branch_count + (1 if lines else 0),
        "cognitive": branch_count + max_brace_depth,
        "nesting_depth": max_brace_depth,
        "function_length": max(function_lengths, default=0),
        "file_length": 0,
    }


def _typescript_function_lengths(lines: list[str]) -> list[int]:
    starts = [
        index
        for index, line in enumerate(lines, start=1)
        if "function " in line or "=>" in line
    ]
    if not starts:
        return []
    lengths: list[int] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] - 1 if position + 1 < len(starts) else len(lines)
        lengths.append(end - start + 1)
    return lengths


class _PythonMetricVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.cyclomatic_values: list[int] = []
        self.cognitive_values: list[int] = []
        self.function_lengths: list[int] = []
        self.max_nesting_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        counter = _PythonFunctionCounter()
        counter.visit(node)
        end_lineno = getattr(node, "end_lineno", node.lineno)
        self.function_lengths.append(end_lineno - node.lineno + 1)
        self.cyclomatic_values.append(counter.cyclomatic)
        self.cognitive_values.append(counter.cognitive)
        self.max_nesting_depth = max(self.max_nesting_depth, counter.max_depth)


class _PythonFunctionCounter(ast.NodeVisitor):
    _BRANCH_NODES = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.ExceptHandler,
        ast.IfExp,
        ast.Match,
    )

    def __init__(self) -> None:
        self.cyclomatic = 1
        self.cognitive = 0
        self.depth = 0
        self.max_depth = 0

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, self._BRANCH_NODES):
            self.cyclomatic += 1
            self.cognitive += 1 + self.depth
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            super().generic_visit(node)
            self.depth -= 1
            return None
        if isinstance(node, ast.BoolOp):
            increment = max(len(node.values) - 1, 0)
            self.cyclomatic += increment
            self.cognitive += increment
        return super().generic_visit(node)
