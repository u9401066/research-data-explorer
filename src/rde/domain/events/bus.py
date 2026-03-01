"""EventBus — Simple synchronous event dispatcher.

Implements a lightweight Pub/Sub pattern for DDD domain events.
Handlers are registered by event type and invoked synchronously
when events are emitted.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from rde.domain.events import DomainEvent

logger = logging.getLogger(__name__)

Handler = Callable[[DomainEvent], None]


class EventBus:
    """Synchronous in-process event bus for domain events."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    def emit(self, event: DomainEvent) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._handlers.get(event.event_type, []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s",
                    handler.__name__,
                    event.event_type,
                )


# ── Singleton ────────────────────────────────────────────────────────

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton (lazy-created)."""
    global _bus
    if _bus is None:
        _bus = EventBus()
        _register_default_handlers(_bus)
    return _bus


def reset_event_bus() -> None:
    """Reset the global bus (for testing)."""
    global _bus
    _bus = None


# ── Default Handlers ─────────────────────────────────────────────────

def _on_pii_detected(event: DomainEvent) -> None:
    """Log PII detection prominently."""
    logger.warning(
        "🔒 PII Detected [%s]: variables=%s",
        event.dataset_id,  # type: ignore[attr-defined]
        event.variable_names,  # type: ignore[attr-defined]
    )


def _on_plan_locked(event: DomainEvent) -> None:
    """Log when analysis plan is locked (irreversible)."""
    logger.info(
        "🔒 Plan LOCKED [project=%s] at %s — deviations must be logged",
        event.project_id,  # type: ignore[attr-defined]
        event.locked_at,  # type: ignore[attr-defined]
    )


def _on_deviation_logged(event: DomainEvent) -> None:
    """Log plan deviations for visibility."""
    logger.warning(
        "⚠️ Plan Deviation [project=%s]: planned='%s' → actual='%s' reason='%s'",
        event.project_id,  # type: ignore[attr-defined]
        event.original_plan,  # type: ignore[attr-defined]
        event.actual_action,  # type: ignore[attr-defined]
        event.reason,  # type: ignore[attr-defined]
    )


def _on_audit_completed(event: DomainEvent) -> None:
    """Log audit grade."""
    logger.info(
        "📋 Audit Completed [project=%s]: grade=%s, completeness=%.0f%%, issues=%d",
        event.project_id,  # type: ignore[attr-defined]
        event.audit_grade,  # type: ignore[attr-defined]
        event.completeness_score * 100,  # type: ignore[attr-defined]
        event.issues_found,  # type: ignore[attr-defined]
    )


def _register_default_handlers(bus: EventBus) -> None:
    """Wire up default cross-cutting handlers."""
    bus.subscribe("security.pii_detected", _on_pii_detected)
    bus.subscribe("plan.locked", _on_plan_locked)
    bus.subscribe("deviation.logged", _on_deviation_logged)
    bus.subscribe("audit.completed", _on_audit_completed)
