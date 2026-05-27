"""Production sloc analyzer backed by ``scc`` (PREQ-A-1).

The ``scc`` binary is downloaded from a pinned GitHub release in the
Dockerfile with ``sha256`` verification at build time; the runtime
``assert_tool_digest`` re-verifies the on-disk binary against
``ScoringSpec.tool_digests['scc']`` before each invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _scc_binary() -> str:
    """Locate the ``scc`` binary path; production image pins this via env."""
    binary = os.environ.get("CCE_SCC_BIN")
    if binary:
        return binary
    found = shutil.which("scc")
    if not found:
        raise RuntimeError(
            "scc backend selected but the 'scc' binary is not on PATH; "
            "set CCE_SCC_BIN or rebuild the production image"
        )
    return found


def analyse(source_path: Path, text: str) -> dict[str, int]:
    binary = _scc_binary()
    # scc is a repo-wide tool; for the analyzer interface we run it against the
    # single file inside a tmp dir to keep determinism per-file.
    with tempfile.TemporaryDirectory(prefix="cce-scc-") as tmp:
        tmp_path = Path(tmp) / source_path.name
        tmp_path.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [binary, "--format", "json", "--no-cocomo", str(tmp_path.parent)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"scc exited with code {result.returncode}: {result.stderr.strip()[:200]}"
        )

    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"scc produced non-JSON output: {exc}") from exc

    code_lines = 0
    complexity = 0
    if isinstance(payload, list):
        for lang in payload:
            if isinstance(lang, dict):
                code_lines = max(code_lines, int(lang.get("Code", 0)))
                complexity = max(complexity, int(lang.get("Complexity", 0)))

    return {
        "cyclomatic": complexity,
        "cognitive": complexity,
        "nesting_depth": 0,
        "function_length": 0,
        "file_length": code_lines,
    }


__all__ = ["analyse"]
