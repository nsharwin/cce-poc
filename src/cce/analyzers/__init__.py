"""Pluggable analyzer backends for CCE.

The default backends (``builtin_python`` and ``builtin_typescript``) preserve
the deterministic POC behavior. ``lizard_runner`` and ``scc_runner`` are
production backends pinned by sha256 digest and verified at runtime
(PREQ-A-1).
"""

from cce.analyzers.registry import (
    AnalyzerBackend,
    AnalyzerRegistry,
    default_registry,
    get_registry,
)

__all__ = [
    "AnalyzerBackend",
    "AnalyzerRegistry",
    "default_registry",
    "get_registry",
]
