from __future__ import annotations

from cce.analyzer import _analyse_typescript


def test_empty_file_returns_zero_metrics() -> None:
    result = _analyse_typescript("")
    assert result["cyclomatic"] == 1
    assert result["cognitive"] == 0
    assert result["nesting_depth"] == 0
    assert result["function_length"] == 0


def test_simple_function_cyclomatic_one() -> None:
    src = """\
function greet(name: string): string {
    return `Hello, ${name}`;
}
"""
    result = _analyse_typescript(src)
    assert result["cyclomatic"] == 1


def test_if_inside_function_increments_cyclomatic() -> None:
    src = """\
function check(x: number): boolean {
    if (x > 0) {
        return true;
    }
    return false;
}
"""
    result = _analyse_typescript(src)
    assert result["cyclomatic"] == 2


def test_nested_if_increments_cognitive_more() -> None:
    src = """\
function nested(x: number, y: number): number {
    if (x > 0) {
        if (y > 0) {
            return x + y;
        }
    }
    return 0;
}
"""
    result = _analyse_typescript(src)
    assert result["cognitive"] >= result["cyclomatic"]
    assert result["nesting_depth"] == 2


def test_function_length_counts_lines() -> None:
    src = """\
function long(): void {
    const a = 1;
    const b = 2;
    const c = 3;
    const d = 4;
}
"""
    result = _analyse_typescript(src)
    assert result["function_length"] == 6


def test_arrow_function_detected() -> None:
    src = """\
const double = (x: number): number => {
    return x * 2;
};
"""
    result = _analyse_typescript(src)
    assert result["function_length"] > 0


def test_deterministic_on_repeated_calls() -> None:
    src = """\
function score(value: number): number {
    if (value > 10) {
        for (let i = 0; i < value; i++) {
            if (i % 2 === 0) {
                return i;
            }
        }
    }
    return 0;
}
"""
    results = [_analyse_typescript(src) for _ in range(10)]
    assert len({str(r) for r in results}) == 1
