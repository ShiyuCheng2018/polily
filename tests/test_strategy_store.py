"""Strategy store — read/write user_strategy table + active_strategy config knob."""
import pytest

from polily.core.db import PolilyDB
from polily.core.strategy_store import (
    get_active_strategy_name,
    get_active_strategy_text,
    get_user_strategy_text,
    load_official_strategy,
    save_user_strategy,
    set_active_strategy,
)


def test_default_active_strategy_is_official(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    assert get_active_strategy_name(db) == "official"


def test_default_user_strategy_is_empty(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    assert get_user_strategy_text(db) == ""


def test_save_user_strategy_writes_text_and_updated_at(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# My strategy\n\nDo things differently.")
    assert get_user_strategy_text(db) == "# My strategy\n\nDo things differently."
    row = db.conn.execute(
        "SELECT updated_at FROM user_strategy WHERE id = 1"
    ).fetchone()
    assert row["updated_at"] != ""  # ISO timestamp written


def test_set_active_strategy_validates_value(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    set_active_strategy(db, "user")
    assert get_active_strategy_name(db) == "user"
    set_active_strategy(db, "official")
    assert get_active_strategy_name(db) == "official"
    with pytest.raises(ValueError):
        set_active_strategy(db, "garbage")


def test_get_active_strategy_text_returns_user_when_active_user(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# My text")
    set_active_strategy(db, "user")
    assert get_active_strategy_text(db) == "# My text"


def test_get_active_strategy_text_returns_user_text_literally_even_when_empty(tmp_path):
    """Q11.5: empty user strategy is injected literally; agent self-falls-back via Read tool."""
    db = PolilyDB(tmp_path / "polily.db")
    set_active_strategy(db, "user")
    # user_strategy.text is '' by default
    assert get_active_strategy_text(db) == ""


def test_get_active_strategy_text_returns_default_md_when_active_official(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    set_active_strategy(db, "official")
    text = get_active_strategy_text(db)
    # default.md ships in package; expect non-empty content
    assert len(text) > 50
    assert "# " in text  # at least one heading


def test_load_official_strategy_returns_packaged_default_md():
    """Read default.md from polily/strategies/."""
    text = load_official_strategy()
    assert len(text) > 50
