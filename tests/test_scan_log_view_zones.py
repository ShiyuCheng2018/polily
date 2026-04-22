"""Menu 0 splits into 待办 / 历史 zones."""
from polily.scan_log import ScanLogEntry
from polily.tui.views.scan_log import _history, _upcoming


def _mk_row(status, scan_id="s1", started="2026-04-10T00:00:00+00:00"):
    return ScanLogEntry(
        scan_id=scan_id, started_at=started, status=status,
        type="analyze", event_id="ev1", market_title="Test",
    )


def test_upcoming_collects_pending_and_running():
    logs = [_mk_row("pending", "a"), _mk_row("completed", "b"), _mk_row("running", "c")]
    upc = _upcoming(logs)
    assert {r.scan_id for r in upc} == {"a", "c"}


def test_history_excludes_pending_and_running():
    logs = [
        _mk_row("pending", "p"), _mk_row("running", "r"),
        _mk_row("completed", "c"), _mk_row("failed", "f"),
        _mk_row("cancelled", "x"), _mk_row("superseded", "s"),
    ]
    hist = _history(logs)
    assert {r.scan_id for r in hist} == {"c", "f", "x", "s"}


def test_history_orders_by_started_at_desc():
    logs = [
        _mk_row("completed", "old", started="2026-01-01T00:00:00+00:00"),
        _mk_row("completed", "new", started="2026-04-10T00:00:00+00:00"),
    ]
    hist = _history(logs)
    assert [r.scan_id for r in hist] == ["new", "old"]


def test_upcoming_orders_running_then_pending_by_schedule():
    """Running on top; pending sorted by scheduled_at asc."""
    r = _mk_row("running", "r")
    p1 = ScanLogEntry(
        scan_id="p_late", started_at="2026-04-10T00:00:00+00:00",
        status="pending", type="analyze", event_id="ev1", market_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
    )
    p2 = ScanLogEntry(
        scan_id="p_soon", started_at="2026-04-10T00:00:00+00:00",
        status="pending", type="analyze", event_id="ev1", market_title="Test",
        scheduled_at="2026-04-20T10:00:00+00:00",
    )
    upc = _upcoming([p1, p2, r])
    assert [e.scan_id for e in upc] == ["r", "p_soon", "p_late"]
