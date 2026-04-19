"""Shared close_event routine — hygiene contract used by recheck and poll_job.

Before this refactor, recheck._close_event and poll_job's inline close did
different things: recheck flipped `event_monitors.auto_monitor=0` and emitted a
notification, poll_job did neither. Now both paths call one shared routine
covered by the tests below.
"""

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, get_event, upsert_event
from scanner.core.monitor_store import get_event_monitor, upsert_event_monitor
from scanner.notifications import get_unread_notifications


def _seed_open_monitored_event(db, event_id="ev1", title="Test Event"):
    upsert_event(EventRow(event_id=event_id, title=title, updated_at="now"), db)
    upsert_event_monitor(event_id, auto_monitor=True, db=db)


def test_close_event_marks_events_row_closed(tmp_path):
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db)

    close_event("ev1", title="Test Event", db=db, trigger_source="poll")

    assert get_event("ev1", db).closed == 1


def test_close_event_disables_auto_monitor(tmp_path):
    """auto_monitor=1 on a closed event is the bug — must flip to 0."""
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db)
    assert get_event_monitor("ev1", db)["auto_monitor"] == 1  # precondition

    close_event("ev1", title="Test Event", db=db, trigger_source="poll")

    assert get_event_monitor("ev1", db)["auto_monitor"] == 0


def test_close_event_writes_notification(tmp_path):
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db, title="US-Iran nuclear deal by April 30?")

    close_event(
        "ev1",
        title="US-Iran nuclear deal by April 30?",
        db=db,
        trigger_source="poll",
    )

    notifs = get_unread_notifications(db)
    assert len(notifs) == 1
    n = notifs[0]
    assert n["title"].startswith("[CLOSED]")
    assert "US-Iran nuclear deal" in n["title"]
    assert n["trigger_source"] == "poll"
    assert n["action_result"] == "closed"
    assert n["event_id"] == "ev1"


def test_close_event_truncates_long_title(tmp_path):
    """Matches existing recheck._close_event behavior — title[:40] in body."""
    from scanner.daemon.close_event import close_event

    long_title = "a" * 120
    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db, title=long_title)

    close_event("ev1", title=long_title, db=db, trigger_source="recheck")

    notifs = get_unread_notifications(db)
    # "[CLOSED] " prefix (9 chars) + 40 chars of title = 49
    assert len(notifs[0]["title"]) == 49


def test_close_event_trigger_source_is_preserved(tmp_path):
    """Both poll_job and recheck call this; trigger_source distinguishes them."""
    from scanner.daemon.close_event import close_event

    db = PolilyDB(tmp_path / "t.db")
    _seed_open_monitored_event(db)

    close_event("ev1", title="T", db=db, trigger_source="recheck")

    notifs = get_unread_notifications(db)
    assert notifs[0]["trigger_source"] == "recheck"
