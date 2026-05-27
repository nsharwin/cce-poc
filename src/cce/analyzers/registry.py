"""Analyzer backend registry with digest-pinned dispatch.

A backend is selected by ``language`` and ``backend_name``. The default
production registry resolves Python and TypeScript via the built-in
analyzers (current POC behavior). Production builds can register
``lizard``/``scc`` runners, which assert their tool digests against
``ScoringSpec.tool_digests`` before each invocation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cce.runtime import assert_tool_digest


class AnalyzerBackend(Protocol):
    """Callable backend that returns ``(metrics, raw_payload)`` for a file."""

    name: str
    tool_digest_key: str | None

    def __call__(self, source_path: Path, source_text: str) -> dict[str, int]: ...


@dataclass
class BackendEntry:
    name: str
    backend: Callable[[Path, str], dict[str, int]]
    tool_digest_key: str | None = None
    binary_resolver: Callable[[], Path] | None = None


@dataclass
class AnalyzerRegistry:
    """Maps ``(language, backend_name)`` to a runner with digest assertion."""

    _entries: dict[tuple[str, str], BackendEntry] = field(default_factory=dict)
    _defaults: dict[str, str] = field(default_factory=dict)

    def register(
        self,
        language: str,
        entry: BackendEntry,
        *,
        default: bool = False,
    ) -> None:
        self._entries[(language, entry.name)] = entry
        if default or language not in self._defaults:
            self._defaults[language] = entry.name

    def resolve(self, language: str, backend_name: str | None = None) -> BackendEntry:
        name = backend_name or self._defaults.get(language)
        if name is None:
            raise KeyError(f"no analyzer backend registered for language={language!r}")
        try:
            return self._entries[(language, name)]
        except KeyError as exc:
            raise KeyError(f"no analyzer backend named {name!r} for language={language!r}") from exc

    def supported_languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._defaults.keys()))

    def assert_digests(self, tool_digests: dict[str, str]) -> None:
        """Verify that every registered backend with a digest key matches the spec."""
        seen: set[str] = set()
        for entry in self._entries.values():
            if entry.tool_digest_key is None or entry.binary_resolver is None:
                continue
            if entry.tool_digest_key in seen:
                continue
            seen.add(entry.tool_digest_key)
            expected = tool_digests.get(entry.tool_digest_key)
            if expected is None:
                raise RuntimeError(f"tool_digests is missing entry {entry.tool_digest_key!r}")
            binary_path = entry.binary_resolver()
            assert_tool_digest(
                name=entry.tool_digest_key,
                expected_digest=expected,
                binary_path=binary_path,
            )


def default_registry() -> AnalyzerRegistry:
    """Return the production-default registry with built-in backends bound.

    Optional backends (``lizard``, ``scc``) are *not* auto-registered here to
    avoid hard dependencies in the POC environment; production images
    register them via :func:`register_production_backends`.
    """
    from cce.analyzers import builtin

    registry = AnalyzerRegistry()
    registry.register(
        language="python",
        entry=BackendEntry(
            name="builtin_ast",
            backend=builtin.analyse_python,
        ),
        default=True,
    )
    registry.register(
        language="typescript",
        entry=BackendEntry(
            name="builtin_tree_sitter",
            backend=builtin.analyse_typescript,
        ),
        default=True,
    )
    return registry


_REGISTRY: AnalyzerRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> AnalyzerRegistry:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = default_registry()
        return _REGISTRY


def reset_registry(registry: AnalyzerRegistry | None = None) -> None:
    """Test hook: replace the process-wide registry."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = registry


def register_production_backends(
    registry: AnalyzerRegistry,
    *,
    lizard_binary: Path | None = None,
    scc_binary: Path | None = None,
) -> AnalyzerRegistry:
    """Bind ``lizard``/``scc`` runners to ``registry`` for production images.

    Called at process start when the analyzer image is the digest-pinned
    production rootfs (see ``Dockerfile``); skipped in the POC dev env.
    """
    if lizard_binary is not None:
        from cce.analyzers import lizard_runner

        registry.register(
            language="python",
            entry=BackendEntry(
                name="lizard",
                backend=lizard_runner.analyse,
                tool_digest_key="lizard",
                binary_resolver=lambda: lizard_binary,
            ),
        )
    if scc_binary is not None:
        from cce.analyzers import scc_runner

        registry.register(
            language="typescript",
            entry=BackendEntry(
                name="scc",
                backend=scc_runner.analyse,
                tool_digest_key="scc",
                binary_resolver=lambda: scc_binary,
            ),
        )
    return registry


__all__ = [
    "AnalyzerBackend",
    "AnalyzerRegistry",
    "BackendEntry",
    "default_registry",
    "get_registry",
    "register_production_backends",
    "reset_registry",
]
