#!/usr/bin/env python3
"""Production entrypoint: bind digest-pinned backends, resolve jailer.json, then exec cce."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from string import Template


_DEFAULT_JAILER_CONFIG = "/opt/cce/ops/firecracker/jailer.json"
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _resolve_jailer_config(env: dict[str, str] | None = None) -> str | None:
    """Read the jailer config, substitute env-var placeholders, write the
    resolved JSON to a temp file, and return the temp path. Returns None when
    the config file does not exist.

    Raises RuntimeError when any placeholder remains unresolved.

    The temp file is intentionally NOT cleaned up — this entrypoint is the
    sole process in a single-shot container, so the file is reaped with the
    container at shutdown.
    """
    env_map = env if env is not None else os.environ
    path = Path(env_map.get("CCE_JAILER_CONFIG", _DEFAULT_JAILER_CONFIG))
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    resolved = Template(raw).safe_substitute(env_map)
    missing = sorted({
        (m.group(1) or m.group(2)) for m in _PLACEHOLDER_RE.finditer(resolved)
        if (m.group(1) or m.group(2)) not in env_map
    })
    if missing:
        raise RuntimeError(
            f"unresolved jailer.json placeholders after env substitution: {missing}"
        )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="jailer-resolved-", delete=False
    ) as tmp:
        tmp.write(resolved)
    return tmp.name


def main() -> None:
    from cce.analyzers.registry import get_registry, register_production_backends
    from cce.cli import entrypoint

    register_production_backends(
        get_registry(),
        lizard_binary=Path("/usr/local/bin/lizard"),
        scc_binary=Path("/usr/local/bin/scc"),
    )
    resolved = _resolve_jailer_config()
    if resolved is not None:
        os.environ["CCE_JAILER_CONFIG_RESOLVED"] = resolved
    entrypoint()


if __name__ == "__main__":
    main()
