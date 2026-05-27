"""Circuit breaker for protecting downstream dependencies (stdlib-only).

After N consecutive failures, the circuit opens for M seconds. During the
open state, requests fast-fail without calling the downstream. After the
recovery timeout, one trial request (half-open) determines whether the
circuit closes again or re-opens.

Used by the service layer to protect ClickHouse writes and Firecracker
boots from cascading failures.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)

_logger = logging.getLogger("cce_service.circuit_breaker")


class CircuitBreakerOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """Thread-safe circuit breaker for a named downstream dependency.

    All state reads and mutations are protected by a :class:`threading.Lock`.
    The downstream function is called *outside* the lock so slow I/O does not
    block concurrent state reads.
    """

    class _State:
        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._lock = threading.Lock()
        self._state = self._State.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def call(self, func: F, *args: object, **kwargs: object) -> object:
        """Execute ``func(*args, **kwargs)`` through the circuit breaker.

        Raises :class:`CircuitBreakerOpenError` if the circuit is open.
        On failure, increments the failure counter and may open the circuit.
        On success in half-open state, resets the circuit back to closed.
        """
        with self._lock:
            self._maybe_transition_locked()
            if self._state == self._State.OPEN:
                raise CircuitBreakerOpenError(
                    f"circuit breaker '{self.name}' is open; fast-failing"
                )

        # Execute func OUTSIDE the lock so slow downstreams don't block state reads.
        try:
            result = func(*args, **kwargs)
        except Exception:
            with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if (
                    self._failure_count >= self.failure_threshold
                    and self._state != self._State.OPEN
                ):
                    self._state = self._State.OPEN
                    _logger.warning(
                        "circuit_breaker.open name=%s failures=%d threshold=%d",
                        self.name,
                        self._failure_count,
                        self.failure_threshold,
                    )
            raise
        else:
            with self._lock:
                if self._state == self._State.HALF_OPEN:
                    self._state = self._State.CLOSED
                    self._failure_count = 0
                    _logger.info(
                        "circuit_breaker.closed name=%s (half-open succeeded)", self.name
                    )
            return result

    def _maybe_transition_locked(self) -> None:
        """Called while ``self._lock`` is held."""
        if self._state == self._State.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = self._State.HALF_OPEN
                _logger.info("circuit_breaker.half_open name=%s", self.name)


__all__ = ["CircuitBreaker", "CircuitBreakerOpenError"]
