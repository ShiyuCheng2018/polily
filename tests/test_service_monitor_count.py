"""v0.10.1 — get_monitor_count must exclude closed events."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polily.core.event_store import EventRow, upsert_event
from polily.core.monitor_store import upsert_event_monitor
from polily.tui.service import PolilyService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = PolilyService()
    yield svc
    svc.db.close()


def _add_event(service, event_id: str, *, closed: bool, auto_monitor: bool) -> None:
    now = datetime.now(UTC).isoformat()
    upsert_event(EventRow(
        event_id=event_id, title=f"Event {event_id}",
        slug=f"e-{event_id}", market_count=1,
        closed=1 if closed else 0,
        active=0 if closed else 1,
        updated_at=now,
    ), service.db)
    upsert_event_monitor(event_id, auto_monitor=auto_monitor, db=service.db)


def test_monitor_count_excludes_closed_events(service):
    """4 monitor=1 events with 2 closed: sidebar count must be 2."""
    _add_event(service, "ev_closed_1", closed=True, auto_monitor=True)
    _add_event(service, "ev_closed_2", closed=True, auto_monitor=True)
    _add_event(service, "ev_active_1", closed=False, auto_monitor=True)
    _add_event(service, "ev_active_2", closed=False, auto_monitor=True)

    assert service.get_monitor_count() == 2
    assert len(service.get_archived_events()) == 2  # symmetric partition


def test_monitor_count_zero_when_no_monitor(service):
    _add_event(service, "ev1", closed=False, auto_monitor=False)
    assert service.get_monitor_count() == 0


def test_monitor_count_all_active_no_closed(service):
    """Sanity — all-active scenario still returns the right count."""
    _add_event(service, "ev1", closed=False, auto_monitor=True)
    _add_event(service, "ev2", closed=False, auto_monitor=True)
    _add_event(service, "ev3", closed=False, auto_monitor=True)
    assert service.get_monitor_count() == 3
