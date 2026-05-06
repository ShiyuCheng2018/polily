"""v0.11.6 concurrency stress test.

v0.11.4 had a deterministic mock-based test (test_db_thread_safety.py)
that proved ONE function structurally acquired db._lock. v0.11.6
extends lock protection to ALL DB access, so this test does what the
v0.11.4 test couldn't: throws real concurrent load at a real PolilyDB
and asserts no sqlite3.InterfaceError ever surfaces.

If this test ever fails, you've found a code path that bypasses
db.transaction() — see test_lock_migration_invariant.py for the
grep-based detection.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from polily.core.db import PolilyDB


@pytest.fixture
def db(tmp_path):
    return PolilyDB(tmp_path / "stress.db")


def _worker(db: PolilyDB, iterations: int, errors: list, op: str):
    """Single thread doing `iterations` ops of type `op`.

    op:
      "read"  — SELECT
      "write" — INSERT
      "mixed" — alternating SELECT / INSERT
    """
    try:
        for i in range(iterations):
            if op == "read" or (op == "mixed" and i % 2 == 0):
                with db.transaction() as conn:
                    conn.execute(
                        "SELECT COUNT(*) FROM wallet_transactions"
                    ).fetchone()
            else:
                with db.transaction() as conn:
                    # Write to a table that exists post-_init_schema.
                    # type='scan' + status='failed' satisfy the CHECK
                    # constraints; started_at must be NOT NULL.
                    conn.execute(
                        "INSERT INTO scan_logs (scan_id, type, status, "
                        "started_at, scheduled_at) "
                        "VALUES (?, 'scan', 'failed', "
                        "'2026-01-01T00:00:00+00:00', "
                        "'2026-01-01T00:00:00+00:00')",
                        (f"stress_{threading.get_ident()}_{i}",),
                    )
    except sqlite3.InterfaceError as e:
        errors.append(("InterfaceError", str(e)))
    except Exception as e:
        errors.append((type(e).__name__, str(e)))


def test_concurrent_mixed_read_write_no_interface_error(db):
    """6 threads × 250 ops = 1500 mixed read/write — no InterfaceError.

    Replaces v0.11.4's mock-based test as the empirical guard against
    the original sqlite3.InterfaceError race. v0.11.4 incident was
    5 ai-executor threads + 1 poll thread; 6 here gives margin.
    """
    errors: list[tuple[str, str]] = []
    threads = [
        threading.Thread(
            target=_worker, args=(db, 250, errors, "mixed"), daemon=True,
        )
        for _ in range(6)
    ]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    elapsed = time.monotonic() - start

    for t in threads:
        assert not t.is_alive(), (
            f"Thread did not finish in 30s — possible deadlock. Elapsed: {elapsed:.1f}s"
        )

    interface_errors = [e for e in errors if e[0] == "InterfaceError"]
    assert not interface_errors, (
        "sqlite3.InterfaceError surfaced under concurrent load — broad "
        "lock migration is incomplete. Errors:\n" +
        "\n".join(f"  {kind}: {msg}" for kind, msg in interface_errors[:5])
    )

    # Other exception types should also be near-zero. Allow 0 errors strictly;
    # if any non-InterfaceError surfaces, surface it (could be a real bug).
    assert not errors, f"Stress run surfaced unexpected errors: {errors[:5]}"


def test_concurrent_pure_writes_no_interface_error(db):
    """2 threads × 200 writes = 400 pure writes — no InterfaceError.

    Pure-write contention is the highest-risk case (SQLite WAL serializes
    writes anyway, but the race was at the Python sqlite3 wrapper layer
    before the lock).
    """
    errors: list[tuple[str, str]] = []
    threads = [
        threading.Thread(
            target=_worker, args=(db, 200, errors, "write"), daemon=True,
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    for t in threads:
        assert not t.is_alive(), "write thread did not finish in 30s"

    assert not errors, (
        "Concurrent writes surfaced errors:\n" +
        "\n".join(f"  {kind}: {msg}" for kind, msg in errors[:5])
    )


def test_concurrent_pure_reads_safe(db):
    """8 threads × 100 reads = 800 reads — no errors. Read-side scaling
    sanity check (reads inside transaction() should still be cheap)."""
    errors: list[tuple[str, str]] = []
    threads = [
        threading.Thread(
            target=_worker, args=(db, 100, errors, "read"), daemon=True,
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    for t in threads:
        assert not t.is_alive(), "read thread did not finish in 30s"

    assert not errors, f"Concurrent reads surfaced errors: {errors[:5]}"
