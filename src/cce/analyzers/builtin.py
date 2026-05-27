"""Built-in analyzer backends for Python (`ast`) and TypeScript (tree-sitter).

These preserve the original POC behavior verbatim so that ``record_hash``
remains byte-identical when no production backend is registered.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import tree_sitter_language_pack
from tree_sitter import Language, Node, Parser

_TS_LANGUAGE: Language | None = None

# Maximum nesting depth for iterative DFS — prevents runaway CPU on
# deeply nested generated / minified TypeScript that would otherwise
# overflow the Python call stack with RecursionError.
_MAX_NESTING_DEPTH = 256

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
        "binary_expression",
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


class AnalyzerError(RuntimeError):
    pass


def _ts_language() -> Language:
    global _TS_LANGUAGE
    if _TS_LANGUAGE is None:
        _TS_LANGUAGE = tree_sitter_language_pack.get_language("typescript")
    return _TS_LANGUAGE


def analyse_python(source_path: Path, text: str) -> dict[str, int]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AnalyzerError(f"failed to parse Python source {source_path}: {exc}") from exc

    visitor = _PythonMetricVisitor()
    visitor.visit(tree)
    return {
        "cyclomatic": max(visitor.cyclomatic_values, default=0),
        "cognitive": max(visitor.cognitive_values, default=0),
        "nesting_depth": visitor.max_nesting_depth,
        "function_length": max(visitor.function_lengths, default=0),
        "file_length": 0,
    }


def analyse_typescript(source_path: Path, text: str) -> dict[str, int]:
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
    """Iterative DFS over the tree-sitter CST to find function definitions.

    Uses an explicit stack to avoid :class:`RecursionError` on deeply
    nested generated / minified TypeScript sources.
    """
    stack: list[tuple[Node, int]] = [(node, 0)]
    while stack:
        current, depth = stack.pop()
        if current.type in _TS_FUNCTION_TYPES:
            cyclomatic, cognitive, max_depth = _count_ts_function(current, source)
            start_line = current.start_point[0] + 1
            end_line = current.end_point[0] + 1
            results.append(
                {
                    "cyclomatic": cyclomatic,
                    "cognitive": cognitive,
                    "nesting_depth": max_depth,
                    "function_length": end_line - start_line + 1,
                }
            )
        if depth >= _MAX_NESTING_DEPTH:
            continue
        for child in reversed(current.children):
            stack.append((child, depth + 1))


def _count_ts_function(node: Node, source: str) -> tuple[int, int, int]:
    """Count cyclomatic and cognitive complexity for a single TS function node.

    Uses iterative DFS with an explicit stack to avoid :class:`RecursionError`
    on deeply nested ASTs.
    """
    cyclomatic = 1
    cognitive = 0
    max_depth = 0

    # Stack entries: (node, depth, processing_mode)
    # mode 0 = normal traversal, mode 1 = skip branch-increment (used when
    # a branch-like node turns out to be a non-branch after type inspection).
    stack: list[tuple[Node, int, bool]] = []

    # Push children in reverse so they're processed left-to-right (same
    # order as the original recursive DFS).
    for child in reversed(node.children):
        stack.append((child, 0, False))

    while stack:
        n, depth, skip_branch = stack.pop()

        # Bail out at nested function boundaries (they're counted separately
        # by _walk_ts_functions).
        if n.type in _TS_FUNCTION_TYPES and n is not node:
            continue

        if depth >= _MAX_NESTING_DEPTH:
            continue

        if n.type in _TS_BRANCH_TYPES:
            if n.type == "binary_expression":
                op_text = ""
                for c in n.children:
                    if not c.is_named or c.type in {"&&", "||", "??"}:
                        candidate = source[c.start_byte : c.end_byte]
                        if candidate in _TS_LOGICAL_OPERATORS:
                            op_text = candidate
                            break
                if op_text not in _TS_LOGICAL_OPERATORS:
                    for child in reversed(n.children):
                        stack.append((child, depth, False))
                    continue
            if n.type == "else_clause":
                child_types = {c.type for c in n.children}
                if "if_statement" in child_types:
                    for child in reversed(n.children):
                        stack.append((child, depth, False))
                    continue
            if not skip_branch:
                cyclomatic += 1
                cognitive += 1 + depth
                new_depth = depth + 1
                if max_depth < new_depth:
                    max_depth = new_depth
                for child in reversed(n.children):
                    stack.append((child, new_depth, False))
                continue

        for child in reversed(n.children):
            stack.append((child, depth, False))

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


__all__ = [
    "AnalyzerError",
    "analyse_python",
    "analyse_typescript",
]
