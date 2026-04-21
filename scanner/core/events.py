# scanner/core/events.py
"""v0.8.0 event bus — service → view pub/sub infrastructure.

Purpose: replace manual `_refresh_*` polling across TUI views. Service
mutations (scan completed, wallet changed, monitor toggled) publish events
to typed topics; views subscribe to topics they care about and update
reactive state on callback.

Threading: handlers are invoked synchronously on the publishing thread.
TUI widgets updating their state from a bus callback MUST use
`self.app.call_from_thread(...)` since the daemon/ScanService may publish
from non-UI threads (daemon executor, analyze worker).

Topics are module-level string constants. Payload shape is per-topic
convention documented at the constant. Keep payloads JSON-serializable-ish
(dicts of primitives) for future extension to IPC.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from collections import defaultdict
from typing import Any, Callable

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


def dispatch_to_ui(app, callable_: Callable[[], Any]) -> None:
    """Invoke a UI-refresh callable safely regardless of the caller thread.

    Textual's `App.call_from_thread` raises when called from the UI event
    loop thread. Pre-v0.8.0 the bus handlers always used it, which meant
    any publisher that happened to run on the UI thread (user button
    click, App.on_mount timer, etc.) had its handler's call_from_thread
    silently raise and be swallowed by `EventBus.publish`'s try/except —
    so the corresponding view never refreshed.

    This helper picks the right dispatch path at call time.
    """
    if threading.current_thread() is threading.main_thread():
        # Already on the UI event loop — schedule via call_later(0, ...) so
        # Textual processes it next tick. Direct call could mount inside
        # an ongoing render and trip DuplicateIds.
        with contextlib.suppress(Exception):
            app.call_later(0, callable_)
        return
    # Worker / daemon / subprocess thread — this is what call_from_thread
    # is designed for.
    with contextlib.suppress(Exception):
        app.call_from_thread(callable_)
