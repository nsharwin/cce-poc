"""Deterministically generate a ~100k LoC Python fixture for POC-GATE-8.

Output is checked into VCS via ``conftest_perf_seed.py`` when run with the
``--write`` flag, but the perf test instead invokes :func:`build_fixture`
into a tmp dir so the repo stays small. The generator is fully
deterministic — no clocks, no randomness — so the produced fixture has a
stable byte content for cross-runner hash comparison.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# 200 files × ~500 lines ≈ 100 000 LoC of valid Python.
DEFAULT_FILES = 200
DEFAULT_FUNCS_PER_FILE = 25
DEFAULT_LINES_PER_FUNC = 20


_FUNC_TEMPLATE = """\
def fn_{idx:06d}(value: int) -> int:
    total = 0
{body}
    return total
"""

_BODY_LINE = "    total += ({n} if value > {n} else value) - {n}\n"


def _render_function(idx: int, lines_per_func: int) -> str:
    body = "".join(_BODY_LINE.format(n=i) for i in range(1, lines_per_func + 1))
    return _FUNC_TEMPLATE.format(idx=idx, body=body)


def build_fixture(
    out_dir: Path,
    *,
    files: int = DEFAULT_FILES,
    funcs_per_file: int = DEFAULT_FUNCS_PER_FILE,
    lines_per_func: int = DEFAULT_LINES_PER_FUNC,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fn_idx = 0
    for file_idx in range(files):
        chunks: list[str] = []
        for _ in range(funcs_per_file):
            chunks.append(_render_function(fn_idx, lines_per_func))
            fn_idx += 1
        (out_dir / f"mod_{file_idx:05d}.py").write_text(
            "".join(chunks), encoding="utf-8"
        )
    return out_dir


def estimated_loc(
    files: int = DEFAULT_FILES,
    funcs_per_file: int = DEFAULT_FUNCS_PER_FILE,
    lines_per_func: int = DEFAULT_LINES_PER_FUNC,
) -> int:
    # Each function = 1 def + N body + 1 return + 1 blank between funcs.
    per_func = lines_per_func + 3
    return files * funcs_per_file * per_func


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--files", type=int, default=DEFAULT_FILES)
    args = parser.parse_args()
    build_fixture(args.out, files=args.files)
    print(f"wrote ~{estimated_loc(files=args.files)} LoC to {args.out}")


if __name__ == "__main__":  # pragma: no cover
    _main()
