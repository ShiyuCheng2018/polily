"""ScanService._query_events returns markets_summary per event."""


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
    from scanner.core.db import PolilyDB
    from scanner.tui.service import ScanService

    db = PolilyDB(tmp_path / "t.db")
    _seed_event_with_markets(db, event_id="e1", market_count=3)

    svc = ScanService(db=db)
    rows = svc.get_all_events()
    assert len(rows) == 1
    ms = rows[0]["markets_summary"]
    assert len(ms) == 3
    assert all(
        "closed" in m and "end_date" in m and "resolved_outcome" in m for m in ms
    )
