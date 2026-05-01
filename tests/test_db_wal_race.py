"""B1 — concurrent PolilyDB construction on a fresh DB file must not crash.

Pre-fix bug: `PRAGMA journal_mode=WAL` runs unconditionally in __init__.
On a fresh DB, when 2+ processes race to construct PolilyDB on the same
path, sqlite returns SQLITE_LOCKED (not SQLITE_BUSY) for the WAL-mode
pragma. busy_timeout only retries BUSY, not LOCKED — so the loser
process hits `sqlite3.OperationalError: database is locked` and crashes.

Repro requires real OS-level processes, not threads (sqlite shares
journal-mode state at the connection level within a single process,
masking the race). Use multiprocessing with the 'spawn' start method
so each worker is a clean Python interpreter, like a real TUI+daemon
launching simultaneously.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path


def _worker_construct_db(db_path: str, result_queue, barrier) -> None:
    """Run in a child process: wait at barrier so all workers hit the
    WAL pragma simultaneously, then construct PolilyDB and report
    success/failure.

    On success, push None onto the queue. On any exception, push the
    exception's repr so the parent can assert on it.
    """
    try:
        # Re-import inside the child so 'spawn' can pickle/load fresh.
        from polily.core.db import PolilyDB

        # Synchronize: every worker waits here until all are ready.
        # Without this, 'spawn' interpreter-startup variance lets the
        # first-launched process finish init before others race in,
        # masking the WAL pragma SQLITE_LOCKED window.
        barrier.wait(timeout=15)

        db = PolilyDB(db_path)
        try:
            # Touch the connection to force the schema script + wallet
            # seed to actually run, surfacing any lock contention.
            db.conn.execute("SELECT id FROM wallet WHERE id = 1").fetchone()
        finally:
            db.close()
        result_queue.put(None)
    except Exception as e:  # noqa: BLE001 — we want to see any failure
        result_queue.put(repr(e))


def _run_concurrent_init(tmp_path: Path, n_workers: int) -> list:
    """Spawn n workers all targeting same db_path. Return list of results
    (None for success, repr of exception for failure)."""
    db_path = str(tmp_path / "polily.db")

    # 'spawn' is the safe cross-platform default (matches macOS 3.8+ default
    # and works on Linux). Avoids fork-related sqlite handle issues.
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    barrier = ctx.Barrier(n_workers)
    procs = [
        ctx.Process(target=_worker_construct_db, args=(db_path, queue, barrier))
        for _ in range(n_workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    # Collect results
    results = []
    while not queue.empty():
        results.append(queue.get_nowait())
    # Make sure every process actually exited cleanly
    for p in procs:
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
    return results


def test_concurrent_polilydb_construction_does_not_crash(tmp_path):
    """4 processes simultaneously constructing PolilyDB on a fresh path —
    none must crash. Pre-fix: 1-3 of them hit `database is locked` from
    the WAL pragma."""
    if sys.platform.startswith("win"):
        # Polily isn't supported on Windows; skip rather than fight
        # multiprocessing semantics differences.
        import pytest
        pytest.skip("multiprocessing semantics differ on Windows")

    results = _run_concurrent_init(tmp_path, n_workers=4)

    # Expect 4 results, all None (success). Pre-fix: at least one would
    # be a non-None exception repr like "OperationalError('database is locked')".
    assert len(results) == 4, f"Expected 4 results, got {results!r}"
    failures = [r for r in results if r is not None]
    assert not failures, (
        f"Concurrent PolilyDB construction crashed: {failures!r}. "
        f"WAL-mode pragma should be idempotent + tolerate concurrent first-init."
    )


def test_concurrent_polilydb_construction_two_processes(tmp_path):
    """Smaller smoke test — 2 processes (the realistic TUI + daemon case)."""
    if sys.platform.startswith("win"):
        import pytest
        pytest.skip("multiprocessing semantics differ on Windows")

    results = _run_concurrent_init(tmp_path, n_workers=2)
    failures = [r for r in results if r is not None]
    assert not failures, f"2-process race crashed: {failures!r}"
