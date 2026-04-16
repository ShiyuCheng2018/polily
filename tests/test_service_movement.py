"""Tests for movement summary in service layer."""

from scanner.monitor.store import get_movement_summary


def test_movement_summary_format(tmp_path):
    """Verify movement summary produces parseable context for AI."""
    from scanner.core.db import PolilyDB
    from scanner.monitor.store import append_movement

    db = PolilyDB(tmp_path / "test.db")
    append_movement(
        event_id="ev1", market_id="m1", magnitude=50.0, quality=40.0, label="noise",
        yes_price=0.50, prev_yes_price=0.48, db=db,
    )
    append_movement(
        event_id="ev1", market_id="m1", magnitude=82.0, quality=71.0, label="consensus",
        yes_price=0.55, prev_yes_price=0.50, triggered_analysis=True, db=db,
    )
    db.conn.commit()

    summary = get_movement_summary("ev1", db, hours=6)
    assert summary is not None
    assert "Movement Log" in summary
    assert "TRIGGERED AI" in summary
    assert "0.55" in summary
    db.close()


def test_get_monitor_count(tmp_path):
    """Verify auto_monitor count query returns correct number."""
    from datetime import UTC, datetime

    from scanner.core.db import PolilyDB
    from scanner.core.monitor_store import get_active_monitors, upsert_event_monitor

    db = PolilyDB(tmp_path / "test.db")
    now = datetime.now(UTC).isoformat()
    # Must insert events first (FK constraint)
    for eid in ("e1", "e2", "e3"):
        db.conn.execute(
            "INSERT INTO events (event_id, title, updated_at) VALUES (?, ?, ?)",
            (eid, f"Event {eid}", now),
        )
    db.conn.commit()

    upsert_event_monitor("e1", auto_monitor=True, db=db)
    upsert_event_monitor("e2", auto_monitor=True, db=db)
    upsert_event_monitor("e3", auto_monitor=False, db=db)

    monitors = get_active_monitors(db)
    assert len(monitors) == 2
    db.close()
