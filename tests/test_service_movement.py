from scanner.movement_store import get_movement_summary


def test_movement_summary_format(tmp_path):
    """Verify movement summary produces parseable context for AI."""
    from scanner.db import PolilyDB
    from scanner.movement import MovementResult
    from scanner.movement_store import append_movement

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
