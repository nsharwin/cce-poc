"""Deterministic tree-sitter span collector shared by the grammar-stability
test and the regeneration script.

Walks only ``node.is_named`` nodes in pre-order DFS (source order). No sorting:
tree-sitter already exposes children in source order, and sorting would corrupt
sibling ordering (e.g. swap if/else branches).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import tree_sitter_language_pack
from tree_sitter import Node, Parser


def collect_spans(path: Path, language: str) -> list[dict[str, Any]]:
    """Return named-node spans for the file at ``path`` parsed as ``language``.

    Each span is a dict with deterministic keys:
    ``type, start_byte, end_byte, start_row, start_col, end_row, end_col``.
    """
    source_bytes = path.read_bytes()
    parser = Parser(tree_sitter_language_pack.get_language(language))
    tree = parser.parse(source_bytes)
    spans: list[dict[str, Any]] = []
    _walk(tree.root_node, spans)
    return spans


def _walk(node: Node, spans: list[dict[str, Any]]) -> None:
    if node.is_named:
        start_row, start_col = node.start_point
        end_row, end_col = node.end_point
        spans.append(
            {
                "type": node.type,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "start_row": start_row,
                "start_col": start_col,
                "end_row": end_row,
                "end_col": end_col,
            }
        )
    for child in node.children:
        _walk(child, spans)
