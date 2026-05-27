"""Unit tests for src/cce/runtime.py (PREQ-A-3 network-isolation self-check)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from cce.runtime import (
    NetworkIsolationError,
    assert_network_isolated,
    is_network_isolated,
)


def test_is_network_isolated_returns_true_when_connect_fails() -> None:
    with patch("cce.runtime.socket.socket") as mk:
        inst = mk.return_value
        inst.connect.side_effect = OSError("Network is unreachable")
        assert is_network_isolated() is True


def test_is_network_isolated_returns_false_when_connect_succeeds() -> None:
    with patch("cce.runtime.socket.socket") as mk:
        inst = mk.return_value
        inst.connect.return_value = None
        assert is_network_isolated() is False


def test_assert_raises_when_network_reachable() -> None:
    with (
        patch("cce.runtime.is_network_isolated", return_value=False),
        pytest.raises(NetworkIsolationError),
    ):
        assert_network_isolated()


def test_assert_silent_when_isolated() -> None:
    with patch("cce.runtime.is_network_isolated", return_value=True):
        assert_network_isolated()  # no raise
