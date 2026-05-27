"""Unit tests for RFC 8785 canonical JSON serialisation (``cce.canonical``)."""

from __future__ import annotations

import json

import pytest

from cce.canonical import canonical_json_bytes, canonical_json_text


def test_simple_dict_is_stable() -> None:
    a = canonical_json_bytes({"b": 1, "a": 2})
    b = canonical_json_bytes({"a": 2, "b": 1})
    assert a == b


def test_nested_dict_ordering() -> None:
    a = canonical_json_bytes({"outer": {"b": 2, "a": 1}})
    b = canonical_json_bytes({"outer": {"a": 1, "b": 2}})
    assert a == b


def test_unicode_strings() -> None:
    value = {"message": "héllo wörld"}
    result = canonical_json_text(value)
    assert "héllo wörld" in result


def test_integers_are_reproducible() -> None:
    result = canonical_json_bytes({"count": 42})
    expected = b'{"count":42}'
    assert result == expected


def test_float_representation() -> None:
    result = canonical_json_bytes({"pi": 3.14})
    # RFC 8785 uses ECMAScript-compatible float format
    parsed = json.loads(result)
    assert abs(parsed["pi"] - 3.14) < 0.01


def test_null_boolean_handling() -> None:
    result = canonical_json_bytes({"a": None, "b": True, "c": False})
    parsed = json.loads(result)
    assert parsed["a"] is None
    assert parsed["b"] is True
    assert parsed["c"] is False


def test_empty_dict_and_list() -> None:
    result = canonical_json_bytes({})
    assert result == b"{}"

    result = canonical_json_bytes([])
    assert result == b"[]"


def test_list_with_mixed_types() -> None:
    result = canonical_json_bytes([1, "two", None, False])
    parsed = json.loads(result)
    assert parsed == [1, "two", None, False]


def test_nested_list_in_dict() -> None:
    result = canonical_json_bytes({"items": [3, 1, 2]})
    parsed = json.loads(result)
    assert parsed["items"] == [3, 1, 2]


def test_special_characters_in_keys() -> None:
    value = {"key.with.dots": 1, "key with spaces": 2}
    result = canonical_json_text(value)
    parsed = json.loads(result)
    assert parsed == value


def test_circular_reference_raises() -> None:
    d: dict = {"self": None}
    d["self"] = d
    with pytest.raises((ValueError, TypeError, RecursionError)):
        canonical_json_bytes(d)


def test_determinism_across_multiple_runs() -> None:
    a = canonical_json_bytes({"c": 3, "b": 2, "a": 1, "d": {"y": 9, "x": 8}})
    b = canonical_json_bytes({"a": 1, "d": {"x": 8, "y": 9}, "b": 2, "c": 3})
    c = canonical_json_bytes({"d": {"y": 9, "x": 8}, "c": 3, "b": 2, "a": 1})
    assert a == b == c
