from __future__ import annotations

from typing import Any

import rfc8785


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 JCS canonical JSON bytes."""
    return rfc8785.dumps(value)


def canonical_json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")
