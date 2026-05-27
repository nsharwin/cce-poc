"""Job dispatchers (in-process for tests, Firecracker for prod)."""

from cce_service.dispatch.base import (
    Dispatcher,
    DispatchError,
    DispatchResult,
    InProcessDispatcher,
)

__all__ = [
    "Dispatcher",
    "DispatchError",
    "DispatchResult",
    "InProcessDispatcher",
]
