from scanner.monitor.store import get_movement_summary


def test_movement_summary_format(tmp_path):
    """Verify movement summary produces parseable context for AI."""
    from scanner.core.db import PolilyDB
    from scanner.monitor.models import MovementResult
    from scanner.monitor.store import append_movement

    db = PolilyDB(tmp_path / "test.db")
    append_movement("m1", MovementResult(magnitude=50.0, quality=40.0),
                    yes_price=0.50, prev_yes_price=0.48, db=db)
    append_movement("m1", MovementResult(magnitude=82.0, quality=71.0),
                    yes_price=0.55, prev_yes_price=0.50, triggered_analysis=True, db=db)

    summary = get_movement_summary("m1", db, hours=6)
    assert summary is not None
    assert "Movement Log" in summary
    assert "TRIGGERED AI" in summary
    assert "0.55" in summary
    db.close()


def test_get_monitor_count(tmp_path):
    """Verify auto_monitor count query returns correct number."""
    from scanner.core.db import PolilyDB
    from scanner.market_state import MarketState, set_market_state

    db = PolilyDB(tmp_path / "test.db")
    set_market_state("m1", MarketState(status="watch", updated_at="2026-04-01", title="A", auto_monitor=True), db)
    set_market_state("m2", MarketState(status="buy_yes", updated_at="2026-04-01", title="B", auto_monitor=True), db)
    set_market_state("m3", MarketState(status="pass", updated_at="2026-04-01", title="C", auto_monitor=False), db)

    count = db.conn.execute("SELECT COUNT(*) FROM market_states WHERE auto_monitor = 1").fetchone()[0]
    assert count == 2
    db.close()
