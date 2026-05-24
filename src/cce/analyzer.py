from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tree_sitter_language_pack
from tree_sitter import Language, Node, Parser

from cce.spec import METRIC_NAMES

_SOURCE_SUFFIXES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__", "cce-out"}

_TS_LANGUAGE: Language | None = None

_TS_BRANCH_TYPES = frozenset(
    {
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "switch_case",
        "switch_default",
        "ternary_expression",
        "catch_clause",
        "binary_expression",  # filtered to && || ?? below
    }
)

_TS_LOGICAL_OPERATORS = frozenset({"&&", "||", "??"})

_TS_FUNCTION_TYPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function_declaration",
        "generator_function",
    }
)


def _ts_language() -> Language:
    global _TS_LANGUAGE
    if _TS_LANGUAGE is None:
        _TS_LANGUAGE = tree_sitter_language_pack.get_language("typescript")
    return _TS_LANGUAGE


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
    if not text.strip():
        return {
            "cyclomatic": 1,
            "cognitive": 0,
            "nesting_depth": 0,
            "function_length": 0,
            "file_length": 0,
        }
    parser = Parser(_ts_language())
    tree = parser.parse(text.encode("utf-8"))

    function_results: list[dict[str, int]] = []
    _walk_ts_functions(tree.root_node, function_results, text)

    if not function_results:
        return {
            "cyclomatic": 1,
            "cognitive": 0,
            "nesting_depth": 0,
            "function_length": 0,
            "file_length": 0,
        }

    return {
        "cyclomatic": max(r["cyclomatic"] for r in function_results),
        "cognitive": max(r["cognitive"] for r in function_results),
        "nesting_depth": max(r["nesting_depth"] for r in function_results),
        "function_length": max(r["function_length"] for r in function_results),
        "file_length": 0,
    }


def _walk_ts_functions(
    node: Node,
    results: list[dict[str, int]],
    source: str,
) -> None:
    if node.type in _TS_FUNCTION_TYPES:
        cyclomatic, cognitive, max_depth = _count_ts_function(node, source)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        results.append(
            {
                "cyclomatic": cyclomatic,
                "cognitive": cognitive,
                "nesting_depth": max_depth,
                "function_length": end_line - start_line + 1,
            }
        )
    for child in node.children:
        _walk_ts_functions(child, results, source)


def _count_ts_function(node: Node, source: str) -> tuple[int, int, int]:
    cyclomatic = 1
    cognitive = 0
    max_depth = 0

    def walk(n: Node, depth: int) -> None:
        nonlocal cyclomatic, cognitive, max_depth
        if n.type in _TS_FUNCTION_TYPES and n is not node:
            return
        if n.type in _TS_BRANCH_TYPES:
            if n.type == "binary_expression":
                op_text = ""
                for c in n.children:
                    if not c.is_named or c.type in {"&&", "||", "??"}:
                        candidate = source[c.start_byte:c.end_byte]
                        if candidate in _TS_LOGICAL_OPERATORS:
                            op_text = candidate
                            break
                if op_text not in _TS_LOGICAL_OPERATORS:
                    for child in n.children:
                        walk(child, depth)
                    return
            if n.type == "else_clause":
                child_types = {c.type for c in n.children}
                if "if_statement" in child_types:
                    for child in n.children:
                        walk(child, depth)
                    return
            cyclomatic += 1
            cognitive += 1 + depth
            new_depth = depth + 1
            if max_depth < new_depth:
                max_depth = new_depth
            for child in n.children:
                walk(child, new_depth)
            return
        for child in n.children:
            walk(child, depth)

    for child in node.children:
        walk(child, 0)
    return cyclomatic, cognitive, max_depth


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
