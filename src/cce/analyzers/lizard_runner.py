"""Production Python analyzer backed by ``lizard`` (PREQ-A-1).

The wheel is hash-pinned in ``requirements.lock.txt`` and the installed
binary path is checked against ``ScoringSpec.tool_digests['lizard']``
before each invocation via ``AnalyzerRegistry.assert_digests``.
"""

from __future__ import annotations

from pathlib import Path


def analyse(source_path: Path, text: str) -> dict[str, int]:
    try:
        import lizard  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - production path only
        raise RuntimeError(
            "lizard backend selected but the 'lizard' package is not installed; "
            "rebuild the production image"
        ) from exc

    analyzer = lizard.analyze_file.analyze_source_code(str(source_path), text)

    cyclomatic = 0
    function_lengths: list[int] = []
    cognitive_proxy = 0
    nesting_depth = 0

    for func in analyzer.function_list:
        cyclomatic = max(cyclomatic, int(func.cyclomatic_complexity))
        function_lengths.append(int(func.length))
        # lizard exposes nloc/parameters but not cognitive complexity; fall back
        # to (CCN-1) as a deterministic proxy that is monotonic with CCN.
        cognitive_proxy = max(cognitive_proxy, max(int(func.cyclomatic_complexity) - 1, 0))
        # lizard reports max nesting in its `top_nesting_level` attribute on
        # newer releases; older releases lack it -> default to 0.
        depth = int(getattr(func, "top_nesting_level", 0))
        nesting_depth = max(nesting_depth, depth)

    return {
        "cyclomatic": cyclomatic,
        "cognitive": cognitive_proxy,
        "nesting_depth": nesting_depth,
        "function_length": max(function_lengths, default=0),
        "file_length": 0,
    }


__all__ = ["analyse"]
