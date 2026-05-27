"""Simple retry decorator with exponential backoff (stdlib-only).

Provides :func:`retry_on_transient_error` for wrapping external calls
that may fail transiently (network blips, DB connection drops, etc.).
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_logger = logging.getLogger("cce_service.retry")


class RetryExhaustedError(RuntimeError):
    pass


def retry_on_transient_error(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    *,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    component: str = "unknown",
) -> Callable[[F], F]:
    """Decorator that retries a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts before raising.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Exception types that trigger a retry.
        component: Human-readable label for log messages.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        _logger.error(
                            "retry.%s exhausted attempts=%d last=%s:%s",
                            component,
                            max_attempts,
                            exc.__class__.__name__,
                            exc,
                        )
                        raise RetryExhaustedError(
                            f"{component}: {max_attempts} attempts exhausted, last error: {exc}"
                        ) from exc
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    _logger.warning(
                        "retry.%s attempt=%d/%d delay=%.1fs error=%s:%s",
                        component,
                        attempt,
                        max_attempts,
                        delay,
                        exc.__class__.__name__,
                        exc,
                    )
                    time.sleep(delay)
            # Should be unreachable but satisfies type checker
            raise RetryExhaustedError(f"{component}: unexpected retry exit") from last_exc

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["RetryExhaustedError", "retry_on_transient_error"]
