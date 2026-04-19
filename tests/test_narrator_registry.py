"""narrator_registry: cross-process cancel primitive for running AI analyses."""
import threading
from unittest.mock import MagicMock

import pytest

from scanner.agents import narrator_registry


@pytest.fixture(autouse=True)
def _clear_registry():
    """Ensure a clean registry between tests — it's module-level state."""
    narrator_registry._active.clear()
    yield
    narrator_registry._active.clear()


def test_register_and_cancel_dispatches_to_narrator():
    narrator = MagicMock()
    narrator_registry.register("sid1", narrator)
    assert narrator_registry.cancel("sid1") is True
    narrator.cancel.assert_called_once()


def test_cancel_unknown_scan_returns_false():
    assert narrator_registry.cancel("nope") is False


def test_unregister_removes_narrator():
    narrator = MagicMock()
    narrator_registry.register("sid2", narrator)
    narrator_registry.unregister("sid2")
    assert narrator_registry.cancel("sid2") is False


def test_registry_is_thread_safe():
    """Two threads register + cancel concurrently — no race on the dict."""
    narrators = [MagicMock() for _ in range(50)]
    for i, n in enumerate(narrators):
        narrator_registry.register(f"sid_{i}", n)

    cancelled: list[bool] = []
    lock = threading.Lock()

    def cancel_some(start, end):
        local = []
        for i in range(start, end):
            local.append(narrator_registry.cancel(f"sid_{i}"))
        with lock:
            cancelled.extend(local)

    t1 = threading.Thread(target=cancel_some, args=(0, 25))
    t2 = threading.Thread(target=cancel_some, args=(25, 50))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert cancelled.count(True) == 50
    assert cancelled.count(False) == 0
