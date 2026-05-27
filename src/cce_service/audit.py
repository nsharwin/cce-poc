"""Helper for building :class:`AuditEvent` rows (REQ-D-5).

Centralised here so every emitter shares the same shape and the
`structured_logger` can mirror them to stdout for log-aggregator backends.
"""

from __future__ import annotations

import logging
from typing import Any

from cce_service.storage import AuditEvent

_logger = logging.getLogger("cce_service.audit")


def audit_event(
    *,
    actor: str,
    action: str,
    target: str,
    tenant: str = "default",
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        action=action,
        target=target,
        tenant=tenant,
        payload=dict(payload or {}),
    )
    _logger.info(
        "audit",
        extra={
            "audit_actor": actor,
            "audit_action": action,
            "audit_target": target,
            "audit_tenant": tenant,
        },
    )
    return event


__all__ = ["audit_event"]
