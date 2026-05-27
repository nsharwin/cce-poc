"""Simple per-tenant token-bucket rate limiter.

In production this is fronted by Redis (so multiple API workers share
state); for tests/dev the in-process implementation is enough and the
public API (:meth:`RateLimiter.allow`) is the same.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    updated: float


class RateLimiter:
    """Token bucket keyed by ``(tenant, bucket_name)``.

    Defaults: 10 requests/sec, burst 20. Both are runtime-tweakable per
    bucket so e.g. the ``score`` bucket can be slower (heavy work) and
    ``records`` faster (point reads).
    """

    DEFAULTS = {
        "score": (5.0, 10),  # 5 rps, burst 10
        "records": (50.0, 100),
        "audit": (10.0, 20),
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def _get_bucket(self, tenant: str, name: str) -> _Bucket:
        key = (tenant, name)
        bucket = self._buckets.get(key)
        if bucket is None:
            refill, capacity = self.DEFAULTS.get(name, (10.0, 20))
            bucket = _Bucket(
                capacity=capacity,
                refill_per_sec=refill,
                tokens=float(capacity),
                updated=time.monotonic(),
            )
            self._buckets[key] = bucket
        return bucket

    def allow(self, tenant: str, name: str) -> bool:
        with self._lock:
            bucket = self._get_bucket(tenant, name)
            now = time.monotonic()
            elapsed = now - bucket.updated
            bucket.tokens = min(
                float(bucket.capacity),
                bucket.tokens + elapsed * bucket.refill_per_sec,
            )
            bucket.updated = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False


__all__ = ["RateLimiter"]
