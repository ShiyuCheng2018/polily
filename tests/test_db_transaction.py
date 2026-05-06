"""Tests for PolilyDB.transaction() — the v0.11.6 canonical access point.

The migration extends v0.11.4's narrow per-function lock to a uniform
context-manager primitive that combines:
  1. self._lock acquisition (RLock — re-entrant safe, same as v0.11.4)
  2. sqlite3 connection's auto-commit / rollback semantic via `with conn:`

All 98 raw db.conn.execute call sites in the codebase migrate to this
primitive in subsequent tasks (Territory 1-4).
"""
from __future__ import annotations

import threading

import pytest

from polily.core.db import PolilyDB


@pytest.fixture
def db(tmp_path):
    return PolilyDB(tmp_path / "transaction-test.db")


def test_transaction_yields_connection(db):
    """The context manager must yield the underlying sqlite3.Connection.

    Migration sites need this — they replace `db.conn.execute(...)` with
    `with db.transaction() as conn: conn.execute(...)`.
    """
    with db.transaction() as conn:
        assert conn is db.conn, (
            "transaction() must yield the same sqlite3.Connection instance "
            "as db.conn — the migration relies on identity"
        )


def test_transaction_acquires_lock(db):
    """Entering transaction() must acquire db._lock; exiting releases it.

    Verified structurally via a counting wrapper around the lock — no
    timing dependencies. Matches v0.11.4's test_db_thread_safety.py
    pattern.
    """
    acquire_count = [0]
    release_count = [0]
    real_lock = db._lock

    class _CountingLock:
        def __enter__(self):
            acquire_count[0] += 1
            return real_lock.__enter__()

        def __exit__(self, *args):
            release_count[0] += 1
            return real_lock.__exit__(*args)

    db._lock = _CountingLock()
    try:
        with db.transaction() as conn:
            conn.execute("SELECT 1")
    finally:
        db._lock = real_lock

    assert acquire_count[0] == 1, (
        f"transaction() must acquire _lock exactly once on entry; "
        f"got {acquire_count[0]} acquires"
    )
    assert release_count[0] == 1, (
        f"transaction() must release _lock exactly once on exit; "
        f"got {release_count[0]} releases"
    )


def test_transaction_commits_on_clean_exit(db):
    """Writes inside `with db.transaction()` must persist after exit.

    Mirrors sqlite3's `with conn:` auto-commit behavior — no manual
    db.conn.commit() needed.
    """
    with db.transaction() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _t2_commit (id INTEGER PRIMARY KEY, v TEXT)",
        )
        conn.execute("INSERT INTO _t2_commit (v) VALUES (?)", ("hello",))
    # New transaction reads what the prior committed
    with db.transaction() as conn:
        rows = conn.execute("SELECT v FROM _t2_commit").fetchall()
    assert len(rows) == 1
    assert rows[0]["v"] == "hello"


def test_transaction_rolls_back_on_exception(db):
    """Exceptions inside `with db.transaction()` must roll the writes back.

    Critical for atomicity contracts (e.g., WalletService.execute_buy
    relying on multi-statement rollback). `with conn:` provides this
    natively.
    """
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS _t2_rollback (id INTEGER PRIMARY KEY, v TEXT)",
    )
    db.conn.commit()

    with pytest.raises(RuntimeError, match="boom"):
        with db.transaction() as conn:
            conn.execute("INSERT INTO _t2_rollback (v) VALUES (?)", ("should_rollback",))
            raise RuntimeError("boom")

    with db.transaction() as conn:
        rows = conn.execute("SELECT v FROM _t2_rollback").fetchall()
    assert rows == [], (
        f"INSERT before RuntimeError must have been rolled back; "
        f"got rows: {[dict(r) for r in rows]}"
    )


def test_transaction_is_reentrant_same_thread(db):
    """Nested `with db.transaction()` on the same thread must NOT deadlock.

    RLock allows re-entry. Without this, any code path that takes the
    lock and indirectly calls something that ALSO takes the lock would
    hang. Critical for WalletService.execute_buy → wallet.debit pattern.
    """
    completed = []

    def _outer():
        with db.transaction() as outer_conn:
            outer_conn.execute("SELECT 1")
            with db.transaction() as inner_conn:
                inner_conn.execute("SELECT 2")
                completed.append("inner")
            completed.append("outer")

    # If the lock were a non-reentrant Lock, this would deadlock forever.
    # We give it a thread + 2s timeout; deadlock manifests as timeout.
    t = threading.Thread(target=_outer, daemon=True)
    t.start()
    t.join(timeout=2.0)

    assert not t.is_alive(), (
        "Re-entrant transaction() deadlocked — _lock must be RLock"
    )
    assert completed == ["inner", "outer"]


def test_nested_transaction_outer_atomicity(db):
    """Whis-review Blocker 1 regression test (2026-05-05).

    The naïve `with self._lock: with self.conn: yield` would commit on
    inner exit, breaking outer atomicity:

        outer with: UPDATE wallet
            inner with: INSERT position  (writes a)
            inner exits → COMMIT (both writes land)
        outer raises → "rollback" is a no-op → money lost

    The corrected implementation detects `conn.in_transaction` and
    yields the same connection without opening a new context. Inner
    exit does NOT commit. Outer rollback rolls back BOTH writes.

    This test reproduces the trade-engine atomicity scenario in
    miniature. If the implementation regresses to the naïve form, this
    test fails with "wallet still debited / partial state landed".
    """
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS _t2_wallet (cash INTEGER NOT NULL)",
    )
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS _t2_positions (shares INTEGER NOT NULL)",
    )
    db.conn.execute("INSERT INTO _t2_wallet (cash) VALUES (100)")
    db.conn.commit()

    def _inner_writes(conn):
        # Simulates wallet.deduct or positions.upsert called from
        # trade_engine — opens its own `with db.transaction()` block.
        with db.transaction() as inner_conn:
            inner_conn.execute("INSERT INTO _t2_positions (shares) VALUES (10)")
        # inner exits — under naïve impl, this would COMMIT outer's
        # cash UPDATE too, leaking the partial state

    with pytest.raises(RuntimeError, match="position-validation-failed"):
        with db.transaction() as outer_conn:
            outer_conn.execute("UPDATE _t2_wallet SET cash = cash - 50")
            _inner_writes(outer_conn)
            # Simulates trade engine raising AFTER inner block — e.g.
            # post-trade validation fails
            raise RuntimeError("position-validation-failed")

    # After outer rollback, wallet must still have $100 AND positions
    # must be empty. If the inner exit committed, wallet would be $50.
    with db.transaction() as conn:
        cash = conn.execute(
            "SELECT cash FROM _t2_wallet"
        ).fetchone()["cash"]
        positions = conn.execute(
            "SELECT shares FROM _t2_positions"
        ).fetchall()

    assert cash == 100, (
        "Wallet was debited ($50 left) — nested `with conn:` "
        "committed prematurely. transaction() must use "
        "`if self.conn.in_transaction: yield` to defer commit "
        "to the outer scope. See Whis-review Blocker 1."
    )
    assert len(positions) == 0, (
        f"Position INSERT survived — outer rollback should have "
        f"rolled it back too. Got {len(positions)} position(s) "
        f"with shares={[r['shares'] for r in positions]}"
    )
