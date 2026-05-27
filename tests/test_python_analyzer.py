"""Unit tests for the Python analyzer (``cce.analyzers.builtin.analyse_python``)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cce.analyzers.builtin import analyse_python


def test_single_function_cyclomatic() -> None:
    text = textwrap.dedent("""\
    def linear(x):
        return x + 1
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] == 1


def test_if_branch_increases_cyclomatic() -> None:
    text = textwrap.dedent("""\
    def branchy(x):
        if x > 0:
            return 1
        elif x < 0:
            return -1
        else:
            return 0
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] == 3  # 1 base + if + elif


def test_loop_increases_cyclomatic() -> None:
    text = textwrap.dedent("""\
    def loopy(x):
        total = 0
        for i in range(x):
            total += i
        return total
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] == 2


def test_nested_branches() -> None:
    text = textwrap.dedent("""\
    def deep(x, y):
        if x > 0:
            for i in range(x):
                if y and i % 2 == 0:
                    print(i)
        return x
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] > 1
    assert result["nesting_depth"] >= 2


def test_multiple_functions_returns_max() -> None:
    text = textwrap.dedent("""\
    def simple():
        return 1

    def complex_func(x, y):
        if x:
            for i in range(3):
                if y and i % 2:
                    return i
        return 0
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] >= 4


def test_syntax_error_raises_analyzer_error() -> None:
    from cce.analyzers.builtin import AnalyzerError

    with pytest.raises(AnalyzerError, match="failed to parse"):
        analyse_python(Path("bad.py"), "def foo(: pass\n")


def test_empty_file_returns_zero_metrics() -> None:
    result = analyse_python(Path("empty.py"), "")
    assert result["cyclomatic"] == 0
    assert result["cognitive"] == 0
    assert result["nesting_depth"] == 0
    assert result["function_length"] == 0
    assert result["file_length"] == 0


def test_function_length_calculation() -> None:
    text = textwrap.dedent("""\
    def short():
        pass

    def longer():
        return 1

    return 2
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["function_length"] > 0


def test_visitor_handles_bool_op() -> None:
    text = textwrap.dedent("""\
    def check(a, b, c):
        if a and b and c:
            return True
        return False
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cyclomatic"] >= 3  # 1 base + if + 2 BoolOp extras


def test_cognitive_depth_penalty() -> None:
    text = textwrap.dedent("""\
    def nested(a):
        if a > 0:
            for i in range(a):
                if i % 2 == 0:
                    pass
        return a
    """)
    result = analyse_python(Path("test.py"), text)
    assert result["cognitive"] > result["cyclomatic"]
