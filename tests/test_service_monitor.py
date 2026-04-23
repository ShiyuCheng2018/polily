"""PolilyService._query_events returns markets_summary per event."""


def _seed_event_with_markets(db, *, event_id="e1", market_count=3):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    db.conn.execute(
        "INSERT INTO events (event_id, title, tags, updated_at) VALUES (?,?,'[]',?)",
        (event_id, "t", now.isoformat()),
    )
    for i in range(market_count):
        closed = 1 if i == 2 else 0
        ed = None if closed else (now + timedelta(days=i + 1)).isoformat()
        db.conn.execute(
            "INSERT INTO markets (market_id, event_id, question, outcomes, "
            "closed, end_date, updated_at) "
            "VALUES (?, ?, 'Q', '[\"Yes\",\"No\"]', ?, ?, ?)",
            (f"m{i}", event_id, closed, ed, now.isoformat()),
        )
    db.conn.commit()


def test_query_events_returns_markets_summary(tmp_path):
    """_query_events must return a compact markets_summary dict per event."""
    from polily.core.db import PolilyDB
    from polily.tui.service import PolilyService

    db = PolilyDB(tmp_path / "t.db")
    _seed_event_with_markets(db, event_id="e1", market_count=3)

    svc = PolilyService(db=db)
    rows = svc.get_all_events()
    assert len(rows) == 1
    ms = rows[0]["markets_summary"]
    assert len(ms) == 3
    assert all(
        "closed" in m and "end_date" in m and "resolved_outcome" in m for m in ms
    )


def test_query_events_reflects_market_state_changes(tmp_path):
    """Subsequent _query_events calls pick up markets_summary changes —
    regression guard that monitor_list's incremental refresh has fresh data
    to consume on each tick."""
    from datetime import UTC, datetime, timedelta

    from polily.core.db import PolilyDB
    from polily.tui.service import PolilyService

    db = PolilyDB(tmp_path / "t.db")
    now = datetime.now(UTC)
    future = (now + timedelta(days=7)).isoformat()
    db.conn.execute(
        "INSERT INTO events (event_id, title, tags, updated_at) VALUES (?,?,'[]',?)",
        ("e1", "t", now.isoformat()),
    )
    db.conn.execute(
        "INSERT INTO markets (market_id, event_id, question, outcomes, "
        "closed, end_date, updated_at) "
        "VALUES ('m1', 'e1', 'Q', '[\"Yes\",\"No\"]', 0, ?, ?)",
        (future, now.isoformat()),
    )
    db.conn.commit()

    svc = PolilyService(db=db)

    # First call: market is open
    rows1 = svc.get_all_events()
    ms1 = rows1[0]["markets_summary"]
    assert ms1[0]["closed"] == 0
    assert ms1[0]["resolved_outcome"] is None

    # Simulate market closure between ticks
    db.conn.execute(
        "UPDATE markets SET closed = 1, resolved_outcome = 'yes' WHERE market_id = 'm1'"
    )
    db.conn.commit()

    # Second call: market is closed with outcome
    rows2 = svc.get_all_events()
    ms2 = rows2[0]["markets_summary"]
    assert ms2[0]["closed"] == 1
    assert ms2[0]["resolved_outcome"] == "yes"
