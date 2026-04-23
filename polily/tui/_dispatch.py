# polily/tui/_dispatch.py
"""Thread-safe dispatch helper for TUI bus handlers.

Lives in the TUI package (not `polily.core.events`) because the
function depends on Textual-specific `App` methods (`call_from_thread`,
`call_later`). `core.events` is meant to stay framework-free so it can
one day extend to IPC between the daemon process and TUI process.

Usage:

    from polily.tui._dispatch import dispatch_to_ui

    class MyView(Widget):
        def _on_price_update(self, payload):
            dispatch_to_ui(self.app, self.refresh_data)

The helper replaces the raw `self.app.call_from_thread(...)` pattern
that silently failed when invoked from the UI event-loop thread (a
publish that happened on the UI thread would raise `RuntimeError` and
`EventBus.publish` would swallow it — see v0.8.0 bus fix).
"""
from __future__ import annotations

import contextlib
import functools
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def once_per_tick(method: Callable) -> Callable:
    """Decorator that coalesces same-instance, same-method calls within a
    tick into a single deferred execution.

    When a view subscribes to N bus topics, a single `_bus_heartbeat`
    fan-out fires its handler N times in the same sync stack. Without
    coalescing, each handler schedules a separate `_render_all` →
    wasted work. This decorator turns N calls into 1 by flipping a
    per-instance, per-method flag on the first call and bailing on
    subsequent ones until the scheduled execution clears it.

    React 18's automatic batching + the `useRef(scheduledFlag) +
    queueMicrotask` pattern, adapted to Textual's dispatch model.

    Must decorate an instance method whose owning class has `self.app`
    pointing at the Textual `App` (same precondition as
    `dispatch_to_ui`).

    Example:

        class MyView(Widget):
            @once_per_tick
            def refresh_data(self):
                self.recompose()

            def _on_price_update(self, payload):
                self.refresh_data()

            def _on_position_update(self, payload):
                self.refresh_data()  # coalesces with the above
    """
    flag_attr = f"_once_per_tick__{method.__name__}"

    @functools.wraps(method)
    def wrapper(self, *args: Any, **kwargs: Any) -> None:
        if getattr(self, flag_attr, False):
            # A refresh is already scheduled for the next tick — bail.
            return
        setattr(self, flag_attr, True)

        # Give the scheduled callable the underlying method's name so
        # debuggers / assertion spies that match on function name
        # (e.g. `"refresh" in fn.__name__`) still see meaningful output.
        @functools.wraps(method)
        def deferred(*da: Any, **dk: Any) -> None:
            # Clear first so a slow `method` call doesn't block the next
            # refresh cycle and so an exception inside method doesn't leave
            # the flag permanently set.
            setattr(self, flag_attr, False)
            method(self, *args, **kwargs)

        try:
            dispatch_to_ui(self.app, deferred)
        except Exception:
            # dispatch_to_ui swallows its own exceptions and returns
            # silently, but if one ever propagates here we'd otherwise
            # leave the flag True forever, blocking all future refreshes.
            setattr(self, flag_attr, False)
            raise

    return wrapper


def dispatch_to_ui(app, callable_: Callable[[], Any]) -> None:
    """Invoke a UI-refresh callable safely regardless of the caller thread.

    Strategy: try `call_from_thread` first and let Textual itself decide.
    If we're on the event-loop thread Textual raises `RuntimeError` and
    we fall through to `call_later(0, ...)` which schedules on the same
    loop's next tick. Delegating the thread check to Textual (rather
    than replicating it with `threading.main_thread()`) is robust across
    app configurations where the event-loop thread isn't the main
    thread — uvloop wrappers, tests launched from helper threads, etc.
    """
    try:
        app.call_from_thread(callable_)
        return
    except RuntimeError:
        # We're on the UI event-loop thread — Textual's own guard fired.
        pass
    except Exception:
        logger.exception("dispatch_to_ui: call_from_thread failed unexpectedly")
        return
    with contextlib.suppress(Exception):
        app.call_later(0, callable_)
