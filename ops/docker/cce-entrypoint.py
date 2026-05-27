#!/usr/bin/env python3
"""Production entrypoint: bind digest-pinned backends, resolve jailer.json, then exec cce."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from string import Template

from cce.analyzers.registry import (
    get_registry,
    register_production_backends,
)
from cce.cli import entrypoint

register_production_backends(
    get_registry(),
    lizard_binary=Path("/usr/local/bin/lizard"),
    scc_binary=Path("/usr/local/bin/scc"),
)

# Resolve jailer.json env-var placeholders.
_JAIKER_PATH = Path(os.environ.get("CCE_JAOKER_CONFIG", "/opt/cce/ops/firecracker/jailer.json"))
if _JAIKER_PATH.exists():
    raw = _JAIKER_PATH.read_text(encoding="utf-8")
    resolved = Template(raw).safe_substitute(os.environ)
    if "sha256:$" in resolved or "${" in resolved:
        missing = [m for m in re.findall(r"\$\{?([^}:\s]+)", resolved) if m in os.environ or m]
        raise RuntimeError(
            f"unresolved jailer.json placeholders after env substitution: {missing}"
        )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="jailer-resolved-", delete=False
    ) as tmp:
        tmp.write(resolved)
    os.environ["CCE_JAIKER_CONFIG_RESOLVED"] = tmp.name

entrypoint()
