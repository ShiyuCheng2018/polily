# polily/core/events.py
"""v0.8.0 event bus — service → view pub/sub infrastructure.

Purpose: replace manual `_refresh_*` polling across TUI views. Service
mutations (scan completed, wallet changed, monitor toggled) publish events
to typed topics; views subscribe to topics they care about and update
reactive state on callback.

Threading: handlers are invoked synchronously on the publishing thread.
TUI widgets updating their state from a bus callback MUST use
`self.app.call_from_thread(...)` since the daemon/PolilyService may publish
from non-UI threads (daemon executor, analyze worker).

Topics are module-level string constants. Payload shape is per-topic
convention documented at the constant. Keep payloads JSON-serializable-ish
(dicts of primitives) for future extension to IPC.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


# --- Topic constants ---
# Payload: {"scan_id": str, "event_id": str, "status": str}
TOPIC_SCAN_UPDATED = "scan.updated"

# Payload: {"balance": float, "txn_count": int}
TOPIC_WALLET_UPDATED = "wallet.updated"

# Payload: {"event_id": str, "auto_monitor": bool}
TOPIC_MONITOR_UPDATED = "monitor.updated"

# Payload: {"market_id": str, "side": str, "size": float}
TOPIC_POSITION_UPDATED = "position.updated"

# Payload: {"event_id": str, "market_id": str, "mid": float, "spread": float}
TOPIC_PRICE_UPDATED = "price.updated"

# Payload: {"language": str}  — emitted when user toggles the active TUI language.
# Subscribers (views, custom Footer) re-render their visible text via t() lookup.
TOPIC_LANGUAGE_CHANGED = "lang.changed"


class EventBus:
    """Thread-safe topic pub/sub. Handlers run synchronously on publish."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subs[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs[topic]:
                self._subs[topic].remove(handler)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            handlers = list(self._subs[topic])  # copy for iteration
        for h in handlers:
            try:
                h(payload)
            except Exception:
                logger.exception("EventBus handler failed for topic=%s", topic)


# Process-wide singleton instance for Service/View to share.
_singleton: EventBus | None = None
_singleton_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide shared EventBus instance."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = EventBus()
    return _singleton


