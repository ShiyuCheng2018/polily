"""Strategy view UX flows (v0.12.0 Task 15).

StrategyView is a self-contained editor: takes a PolilyDB, renders a radio
toggle (official | user), a TextArea (user mode) or Markdown render
(official mode), starter buttons (only when user-text is empty), and
save/discard buttons. Active-strategy persists via strategy_store.
"""
from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Button, RadioButton, RadioSet, TextArea

from polily.core.db import PolilyDB
from polily.core.strategy_store import (
    get_active_strategy_name,
    get_user_strategy_text,
    save_user_strategy,
)
from polily.tui.views.strategy import StrategyView


@pytest.mark.asyncio
async def test_radio_default_official(tmp_path):
    """Fresh DB → active_strategy defaults to 'official' → first radio selected."""
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        rs = pilot.app.query_one(RadioSet)
        buttons = list(rs.query(RadioButton))
        assert buttons, "RadioSet should have RadioButton children"
        # First button (official) should be selected
        assert buttons[0].value is True


@pytest.mark.asyncio
async def test_toggle_to_user_with_empty_text_shows_two_buttons(tmp_path):
    """Empty user_strategy.text → both starter buttons visible after select_user."""
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        button_labels = []
        for b in pilot.app.query(Button):
            label = b.label.plain if hasattr(b.label, "plain") else str(b.label)
            button_labels.append(label.lower())
        labels_str = " ".join(button_labels)
        assert any(token in labels_str for token in ("scratch", "blank", "空白"))
        assert any(token in labels_str for token in ("official", "default", "官方"))


@pytest.mark.asyncio
async def test_save_writes_user_strategy_to_db(tmp_path):
    """User mode + edited textarea + action_save() → strategy_store persists text."""
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        ta = pilot.app.query_one(TextArea)
        ta.text = "# My custom strategy\n\nWith content."
        view.action_save()
        await pilot.pause()
        assert get_user_strategy_text(db) == "# My custom strategy\n\nWith content."


@pytest.mark.asyncio
async def test_radio_toggle_persists_active_strategy(tmp_path):
    """select_user() / select_official() each persist to active_strategy config."""
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# user content")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        assert get_active_strategy_name(db) == "user"
        view.action_select_official()
        await pilot.pause()
        assert get_active_strategy_name(db) == "official"
