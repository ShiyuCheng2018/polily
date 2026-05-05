"""BUG-4: assert PolilyDB exposes _lock + dispatcher acquires it
inside _run_pending_analysis.

This is NOT a race-condition reproduction test (those are notoriously
flaky). It's a structural test: if `db._lock` is held during
_run_pending_analysis, the InterfaceError race observed in prod
2026-05-04 21:38 is by-construction prevented (single-threaded
critical section).

Real prod evidence in `daemon-stderr.log`:
- sqlite3.InterfaceError: bad parameter or other API misuse
  at polily/core/event_store.py:152 (db.conn.execute)
- 2 ai threads racing get_event() concurrently produced this
"""
from __future__ import annotations

import threading


def test_polily_db_has_rlock_not_lock(polily_db):
    """PolilyDB._lock must be a re-entrant lock so __init__ can take
    it without deadlock. threading.RLock has __enter__/_release_ + a
    _RLock-specific recursion attribute."""
    assert hasattr(polily_db, "_lock"), (
        "PolilyDB must expose self._lock for v0.11.4 BUG-4 fix"
    )
    # threading.RLock objects expose `_count` (recursion depth tracker);
    # threading.Lock objects do not. This is the cleanest discriminator
    # without depending on private API surface.
    assert isinstance(polily_db._lock, type(threading.RLock())), (
        f"PolilyDB._lock must be threading.RLock, got "
        f"{type(polily_db._lock).__name__}. Lock (non-reentrant) would "
        f"deadlock if __init__ recursively acquires while doing PRAGMA "
        f"setup or schema migration."
    )


def test_run_pending_analysis_acquires_db_lock(polily_db, monkeypatch):
    """_run_pending_analysis body must execute inside `with db._lock:`.
    Replace polily_db._lock with a MagicMock to count acquires/releases."""
    from datetime import UTC, datetime

    from polily.daemon import poll_job
    from polily.scan_log import claim_pending_scan, insert_pending_scan

    # Seed minimal event + pending scan_logs row
    polily_db.conn.execute(
        "INSERT INTO events(event_id, title, slug, market_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("evt_lock_test", "Lock test", "lt", 1, datetime.now(UTC).isoformat()),
    )
    insert_pending_scan(
        event_id="evt_lock_test",
        event_title="Lock test",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="movement",
        scheduled_reason="test",
        db=polily_db,
    )
    row = polily_db.conn.execute(
        "SELECT scan_id FROM scan_logs WHERE event_id=?", ("evt_lock_test",),
    ).fetchone()
    scan_id = row["scan_id"]
    assert claim_pending_scan(scan_id, polily_db)

    # Replace db._lock with a context-manager mock that counts entries
    enter_count = {"n": 0}
    exit_count = {"n": 0}

    class _CountingLock:
        def __enter__(self):
            enter_count["n"] += 1
            return self
        def __exit__(self, *a):
            exit_count["n"] += 1
            return None

    polily_db._lock = _CountingLock()

    # Monkey-patch PolilyService to immediately raise so we don't have
    # to set up a real claude subprocess; we only care about lock entry
    from polily.tui.service import PolilyService
    monkeypatch.setattr(
        PolilyService, "__init__",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("simulated")),
    )

    class _FakeCtx:
        config = None
        scheduler = None
    monkeypatch.setattr(poll_job, "_ctx", _FakeCtx())

    poll_job._run_pending_analysis(
        event_id="evt_lock_test",
        scan_id=scan_id,
        db=polily_db,
        trigger_source="movement",
    )

    assert enter_count["n"] >= 1, (
        f"_run_pending_analysis must acquire db._lock at least once. "
        f"enter_count={enter_count['n']}, exit_count={exit_count['n']}. "
        f"Without this, the prod race observed 2026-05-04 21:38 "
        f"(sqlite3.InterfaceError) is not prevented."
    )
    assert exit_count["n"] == enter_count["n"], (
        "Lock acquired but not released — leak"
    )
