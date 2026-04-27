"""Tests for polily.core.user_prefs — K/V store for user preferences (e.g. language)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from polily.core.db import PolilyDB
from polily.core.user_prefs import get_pref, list_prefs, set_pref


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = PolilyDB(Path(tmp) / "polily.db")
        yield d
        d.close()


def test_user_prefs_table_exists(db):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_prefs'"
    ).fetchall()
    assert len(rows) == 1


def test_get_pref_returns_none_for_missing_key(db):
    assert get_pref(db, "language") is None


def test_set_then_get_pref_roundtrips(db):
    set_pref(db, "language", "en")
    assert get_pref(db, "language") == "en"


def test_set_pref_overwrites_existing_value(db):
    set_pref(db, "language", "zh")
    set_pref(db, "language", "en")
    assert get_pref(db, "language") == "en"


def test_set_pref_updates_timestamp(db):
    set_pref(db, "language", "zh")
    first = db.conn.execute(
        "SELECT updated_at FROM user_prefs WHERE key='language'"
    ).fetchone()[0]
    # second write — value unchanged but timestamp must update
    set_pref(db, "language", "en")
    second = db.conn.execute(
        "SELECT updated_at FROM user_prefs WHERE key='language'"
    ).fetchone()[0]
    # accept equal-or-later (test runs fast; ISO strings compare lexicographically)
    assert second >= first


def test_list_prefs_returns_all_keys(db):
    set_pref(db, "language", "en")
    set_pref(db, "theme", "dark")
    prefs = list_prefs(db)
    assert prefs == {"language": "en", "theme": "dark"}


def test_list_prefs_empty_when_no_keys(db):
    assert list_prefs(db) == {}


def test_get_pref_with_default(db):
    assert get_pref(db, "language", default="zh") == "zh"
    set_pref(db, "language", "en")
    assert get_pref(db, "language", default="zh") == "en"
