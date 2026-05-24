"""Strategy view UX flows (v0.12.0 Task 15).

StrategyView is a self-contained editor: takes a PolilyDB, renders a radio
toggle (official | user), a TextArea (user mode) or Markdown render
(official mode), starter buttons (only when user-text is empty), and
save/discard buttons. Active-strategy persists via strategy_store.
"""
from __future__ import annotations

import pytest
from textual.app import App
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Markdown, RadioButton, RadioSet, TextArea

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
async def test_official_markdown_wrapped_in_vertical_scroll(tmp_path):
    """v0.12.0 hotfix: the official-strategy Markdown widget must be wrapped
    in a VerticalScroll so the ~95-line default.md is browsable. Without
    this, Markdown has no internal scroll and content past the viewport is
    unreachable.
    """
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        # The Markdown widget exists
        md = view.query_one("#strategy-readonly", Markdown)
        # And its parent (or grandparent up the tree) is a VerticalScroll
        scroll_wrapper = view.query_one("#strategy-readonly-scroll", VerticalScroll)
        # Markdown is inside the scroll wrapper (Textual's parent / region check)
        assert md in scroll_wrapper.walk_children(Markdown), (
            "Markdown widget must be a descendant of VerticalScroll wrapper "
            "for the official strategy to be scrollable"
        )


@pytest.mark.asyncio
async def test_user_mode_hides_scroll_wrapper(tmp_path):
    """User mode shows TextArea, not the official-strategy scroll wrapper.

    Toggling display.False on the wrapper (not the inner Markdown) is critical
    — toggling Markdown alone would leave the empty wrapper consuming layout
    space.
    """
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        scroll_wrapper = view.query_one("#strategy-readonly-scroll", VerticalScroll)
        assert scroll_wrapper.display is False, (
            "VerticalScroll wrapper must be hidden in user mode "
            "(otherwise it occupies layout space alongside the TextArea)"
        )
        ta = view.query_one("#strategy-textarea", TextArea)
        assert ta.display is True


@pytest.mark.asyncio
async def test_radio_labels_react_to_language_switch(tmp_path):
    """Radio button labels must come from the i18n catalog so switching
    language (F2 → set_language) updates them on next compose. Asserts
    en + zh both round-trip through t() without falling back to key strings.
    """
    from polily.tui.i18n import set_language, t

    db = PolilyDB(tmp_path / "polily.db")
    # Fresh state — capture both languages' catalog entries directly
    set_language("en")
    en_official = t("strategy.radio_official_label")
    en_user = t("strategy.radio_user_label")
    set_language("zh")
    zh_official = t("strategy.radio_official_label")
    zh_user = t("strategy.radio_user_label")

    # Catalog entries differ between languages (no key-string fallback)
    assert en_official != zh_official, (
        f"en + zh strategy.radio_official_label collapsed to same value "
        f"({en_official!r}) — likely a missing catalog entry"
    )
    assert en_user != zh_user
    # Neither falls back to the bare key string
    for label in (en_official, en_user, zh_official, zh_user):
        assert label != "strategy.radio_official_label"
        assert label != "strategy.radio_user_label"

    # And the rendered radio buttons in zh-mode actually show the zh label
    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        rs = pilot.app.query_one(RadioSet)
        buttons = list(rs.query(RadioButton))
        # First button is "official" — its label should match the zh catalog entry
        first_label = buttons[0].label.plain if hasattr(buttons[0].label, "plain") else str(buttons[0].label)
        assert first_label == zh_official, (
            f"RadioButton label {first_label!r} doesn't match zh catalog entry {zh_official!r}"
        )

    # Restore
    set_language("en")


@pytest.mark.asyncio
async def test_live_language_switch_updates_visible_labels(tmp_path):
    """Pressing F2 to switch language while StrategyView is mounted MUST
    update the visible radio + button labels in-place. Without subscribing
    to TOPIC_LANGUAGE_CHANGED, t() lookups happen only at compose time —
    labels freeze at whatever language was loaded when the view was
    first mounted, which the user perceives as 'hardcoded'.

    Pattern: same as wallet.py / event_detail.py / archived_events.py —
    subscribe in on_mount, unsubscribe in on_unmount, handler reaches
    into mounted widgets and re-applies t() values.
    """
    from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
    from polily.tui.i18n import set_language, t

    db = PolilyDB(tmp_path / "polily.db")

    set_language("en")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        rs = pilot.app.query_one(RadioSet)
        buttons = list(rs.query(RadioButton))
        save_btn = pilot.app.query_one("#btn-save", Button)
        discard_btn = pilot.app.query_one("#btn-discard", Button)

        # Sanity: en mode shows en labels
        en_official_label = buttons[0].label.plain if hasattr(buttons[0].label, "plain") else str(buttons[0].label)
        assert en_official_label == t("strategy.radio_official_label")

        # Switch language and broadcast (mimics action_toggle_language)
        set_language("zh")
        get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": "zh"})
        await pilot.pause()

        # Re-query (labels are mutable on existing widgets, no re-mount)
        zh_official_label = buttons[0].label.plain if hasattr(buttons[0].label, "plain") else str(buttons[0].label)
        zh_user_label = buttons[1].label.plain if hasattr(buttons[1].label, "plain") else str(buttons[1].label)
        zh_save_label = save_btn.label.plain if hasattr(save_btn.label, "plain") else str(save_btn.label)
        zh_discard_label = discard_btn.label.plain if hasattr(discard_btn.label, "plain") else str(discard_btn.label)

        # All four MUST now match the zh catalog
        assert zh_official_label == t("strategy.radio_official_label"), (
            f"Radio 'official' label still {zh_official_label!r} after language switch — "
            f"StrategyView is not subscribing to TOPIC_LANGUAGE_CHANGED"
        )
        assert zh_user_label == t("strategy.radio_user_label")
        assert zh_save_label == t("strategy.save_button")
        assert zh_discard_label == t("strategy.discard_button")

    # Restore for other tests
    set_language("en")


@pytest.mark.asyncio
async def test_starter_button_labels_react_to_language_switch(tmp_path):
    """Starter buttons (only visible in user mode with empty text) must also
    react to language switch — they're separate from the always-mounted
    save/discard pair.
    """
    from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
    from polily.tui.i18n import set_language, t

    db = PolilyDB(tmp_path / "polily.db")
    set_language("en")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        # Switch to user mode so starter buttons render
        view.action_select_user()
        await pilot.pause()

        blank_btn = pilot.app.query_one("#btn-blank", Button)
        copy_btn = pilot.app.query_one("#btn-copy-official", Button)

        # Switch language while starter buttons are visible
        set_language("zh")
        get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": "zh"})
        await pilot.pause()

        zh_blank = blank_btn.label.plain if hasattr(blank_btn.label, "plain") else str(blank_btn.label)
        zh_copy = copy_btn.label.plain if hasattr(copy_btn.label, "plain") else str(copy_btn.label)

        assert zh_blank == t("strategy.starter_blank_button")
        assert zh_copy == t("strategy.starter_copy_official_button")

    set_language("en")


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


# ---------------------------------------------------------------------------
# v0.12.3 — 3-mode state machine (official / user_view / user_edit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_with_existing_text_starts_in_view_mode(tmp_path):
    """When user_strategy is non-empty, entering user mode lands in user_view
    (Markdown rendered, [Edit] button visible, TextArea hidden). This is the
    bug fix for v0.12.0's behavior of always going straight to edit mode.
    """
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# My strategy\n\nDo things differently.")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        assert view._mode == "user_view"
        # Markdown widget visible with the user's content (content asserted
        # in test_user_view_markdown_content_matches_saved_strategy; here
        # we only check the visibility wiring)
        ro_scroll = view.query_one("#strategy-readonly-scroll", VerticalScroll)
        assert ro_scroll.display is True
        # TextArea hidden
        ta = view.query_one("#strategy-textarea", TextArea)
        assert ta.display is False
        # Edit button visible; Save/Cancel hidden
        assert view.query_one("#btn-edit", Button).display is True
        assert view.query_one("#btn-save", Button).display is False
        assert view.query_one("#btn-discard", Button).display is False


@pytest.mark.asyncio
async def test_empty_user_strategy_starts_in_edit_mode(tmp_path):
    """When user_strategy is empty, entering user mode lands in user_edit
    (no Markdown to view). Edit-empty shows the starter row.
    """
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        assert view._mode == "user_edit"
        assert view.query_one("#strategy-textarea", TextArea).display is True
        assert view.query_one("#starter-row", Horizontal).display is True
        # Save/Cancel visible; Edit hidden in edit mode
        assert view.query_one("#btn-edit", Button).display is False
        assert view.query_one("#btn-save", Button).display is True
        assert view.query_one("#btn-discard", Button).display is True


@pytest.mark.asyncio
async def test_edit_action_transitions_view_to_edit(tmp_path):
    """From user_view, action_enter_edit() switches to user_edit and
    populates the TextArea with the saved content.
    """
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# existing content")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        assert view._mode == "user_view"

        view.action_enter_edit()
        await pilot.pause()
        assert view._mode == "user_edit"
        ta = view.query_one("#strategy-textarea", TextArea)
        assert ta.display is True
        # TextArea pre-filled with current content (the whole point of
        # the Edit → TextArea transition)
        assert ta.text == "# existing content"


@pytest.mark.asyncio
async def test_save_returns_to_view_mode(tmp_path):
    """After save with non-empty content, the view lands back in user_view
    (Markdown rendering the just-saved content), not stuck in edit.
    """
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()  # lands in user_edit (empty DB)
        await pilot.pause()
        ta = view.query_one("#strategy-textarea", TextArea)
        ta.text = "# Saved content"
        view.action_save()
        await pilot.pause()
        # Persisted
        assert get_user_strategy_text(db) == "# Saved content"
        # Transitioned to view mode
        assert view._mode == "user_view"
        ro_scroll = view.query_one("#strategy-readonly-scroll", VerticalScroll)
        assert ro_scroll.display is True
        assert view.query_one("#btn-edit", Button).display is True


@pytest.mark.asyncio
async def test_save_empty_stays_in_edit(tmp_path):
    """Edge case: saving an empty TextArea (user cleared everything) leaves
    the view in user_edit (because there's nothing to view) — consistent
    with the "open empty DB → user_edit" rule.
    """
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# something")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        view.action_enter_edit()
        await pilot.pause()
        ta = view.query_one("#strategy-textarea", TextArea)
        ta.text = ""  # user cleared everything
        view.action_save()
        await pilot.pause()
        assert view._mode == "user_edit"
        assert get_user_strategy_text(db) == ""


@pytest.mark.asyncio
async def test_dirty_detection_returns_true_when_textarea_differs(tmp_path):
    """_is_dirty() returns True iff TextArea content differs from saved
    user_strategy. Used by Cancel + radio-toggle to decide whether to ask
    for confirmation.
    """
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# original")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        view.action_enter_edit()
        await pilot.pause()

        # Just entered edit — text matches saved → not dirty
        assert view._is_dirty() is False

        ta = view.query_one("#strategy-textarea", TextArea)
        ta.text = "# original\n\nadded a line"
        assert view._is_dirty() is True

        # Revert to original
        ta.text = "# original"
        assert view._is_dirty() is False


@pytest.mark.asyncio
async def test_dirty_check_skipped_outside_edit_mode(tmp_path):
    """_is_dirty() is meaningful only in user_edit. Other modes (official,
    user_view) always return False — no edit buffer to compare against.
    """
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# saved")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        # Initially official → not dirty
        assert view._is_dirty() is False
        # user_view → not dirty
        view.action_select_user()
        await pilot.pause()
        assert view._mode == "user_view"
        assert view._is_dirty() is False


@pytest.mark.asyncio
async def test_official_mode_hides_all_edit_buttons(tmp_path):
    """Official mode is purely read-only — no edit/save/cancel affordances.
    Prevents the v0.12.0 layout-bug of dangling buttons under read-only
    content.
    """
    db = PolilyDB(tmp_path / "polily.db")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        # Default state is official
        assert view._mode == "official"
        assert view.query_one("#btn-edit", Button).display is False
        assert view.query_one("#btn-save", Button).display is False
        assert view.query_one("#btn-discard", Button).display is False
        assert view.query_one("#starter-row", Horizontal).display is False
        # And the Markdown is rendering with content
        ro_scroll = view.query_one("#strategy-readonly-scroll", VerticalScroll)
        assert ro_scroll.display is True


@pytest.mark.asyncio
async def test_user_view_markdown_content_matches_saved_strategy(tmp_path):
    """The user_view Markdown widget is populated with the actual saved
    user_strategy text (not the official strategy or an empty placeholder).
    This is the direct fix for the v0.12.0 bug of TextArea showing raw
    markdown source instead of rendered output.
    """
    db = PolilyDB(tmp_path / "polily.db")
    user_md = "# Custom strategy\n\n## My priorities\n\n- focus on X\n- avoid Y"
    save_user_strategy(db, user_md)

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        # In user_view; the Markdown widget should be populated with the
        # user's actual saved content (not load_official_strategy()).
        # Textual's Markdown widget exposes the source via `.source`.
        md = view.query_one("#strategy-readonly", Markdown)
        assert md.source == user_md, (
            f"Expected Markdown.source to render the saved user strategy, "
            f"got {md.source!r}"
        )


@pytest.mark.asyncio
async def test_edit_button_label_reacts_to_language_switch(tmp_path):
    """Same pattern as starter/save/discard: the new btn-edit must subscribe
    to TOPIC_LANGUAGE_CHANGED so its label flips on F2 language toggle.
    """
    from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
    from polily.tui.i18n import set_language, t

    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# something")
    set_language("en")

    class T(App):
        def compose(self):
            yield StrategyView(db)

    async with T().run_test() as pilot:
        view = pilot.app.query_one(StrategyView)
        view.action_select_user()
        await pilot.pause()
        edit_btn = view.query_one("#btn-edit", Button)
        en_label = (
            edit_btn.label.plain if hasattr(edit_btn.label, "plain")
            else str(edit_btn.label)
        )
        assert en_label == t("strategy.edit_button")

        set_language("zh")
        get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": "zh"})
        await pilot.pause()

        zh_label = (
            edit_btn.label.plain if hasattr(edit_btn.label, "plain")
            else str(edit_btn.label)
        )
        assert zh_label == t("strategy.edit_button")
        assert en_label != zh_label, (
            "edit_button label should differ between en and zh "
            "(otherwise catalog entry missing)"
        )

    set_language("en")
