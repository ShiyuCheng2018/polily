"""Shared close_event routine — hygiene contract used by recheck and poll_job.

Before this refactor, recheck._close_event and poll_job's inline close did
different things: recheck flipped `event_monitors.auto_monitor=0` and emitted a
notification, poll_job did neither. Now both paths call one shared routine
covered by the tests below.
"""

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, get_event, upsert_event
from scanner.core.monitor_store import get_event_monitor, upsert_event_monitor


def _seed_open_monitored_event(db, event_id="ev1", title="Test Event"):
    upsert_event(EventRow(event_id=event_id, title=title, updated_at="now"), db)
    upsert_event_monitor(event_id, auto_monitor=True, db=db)


def test_close_event_marks_events_row_closed(tmp_path):
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db)

    close_event("ev1", title="Test Event", db=db, trigger_source="poll")

    assert get_event("ev1", db).closed == 1


def test_close_event_preserves_auto_monitor_as_user_intent(tmp_path):
    """auto_monitor is a **user intent** flag — "did the user choose to
    monitor this event" — not a "currently being polled" flag. It must not
    be flipped by `close_event`; preserving it lets the Archive view filter
    on "events the user was monitoring when they closed".
    """
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db)
    assert get_event_monitor("ev1", db)["auto_monitor"] == 1  # precondition

    close_event("ev1", title="Test Event", db=db, trigger_source="poll")

    assert get_event_monitor("ev1", db)["auto_monitor"] == 1


def test_close_event_preserves_explicit_auto_monitor_zero(tmp_path):
    """If the user had already turned monitoring off, close_event doesn't
    re-enable it — preservation means "whatever the user set stays"."""
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="T", updated_at="now"), db)
    upsert_event_monitor("ev1", auto_monitor=False, db=db)

    close_event("ev1", title="T", db=db, trigger_source="poll")

    assert get_event_monitor("ev1", db)["auto_monitor"] == 0
