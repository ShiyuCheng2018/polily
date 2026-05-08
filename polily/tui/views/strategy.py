"""Strategy editor view — radio toggle (official | user), TextArea, save/discard.

v0.12.0 — single-slot user strategy editor at TUI key `7`. Radio toggle
between Official (read-only render of packaged default.md) and My Strategy
(editable TextArea backed by user_strategy table). First-time empty-user
state shows two starter buttons (blank / copy-official). Hot-swap radio
takes effect on next analysis dispatch (per design Q7).

Why not surface starter buttons via a modal: the plan specs an in-page
two-button row that disappears once the user picks one (or types). A
modal would force a forced-choice dialog and break the "same page,
different content" mental model the radio toggle establishes.
"""
from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Markdown, RadioButton, RadioSet, TextArea

from polily.core.db import PolilyDB
from polily.core.strategy_store import (
    get_active_strategy_name,
    get_user_strategy_text,
    load_official_strategy,
    save_user_strategy,
    set_active_strategy,
)
from polily.tui.i18n import t


class StrategyView(Vertical):
    """v0.12.0 Strategy page — single-slot user strategy editor."""

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
    ]

    DEFAULT_CSS = """
    StrategyView {
        padding: 1 2;
    }
    StrategyView .starter-row {
        height: auto;
        padding: 1 0;
    }
    StrategyView .starter-row Button {
        margin: 0 1;
    }
    StrategyView TextArea, StrategyView Markdown {
        height: 1fr;
    }
    StrategyView .button-row {
        height: 3;
        align: left middle;
    }
    StrategyView .button-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, db: PolilyDB, **kwargs) -> None:
        super().__init__(**kwargs)
        self._db = db
        self._dirty = False
        # Suppress on_radio_set_changed during initial compose (Textual fires
        # Changed when the initial selected RadioButton is mounted, which
        # would re-write the same active_strategy value and fire a toast).
        self._suppress_radio_event = True

    def compose(self) -> ComposeResult:
        active = get_active_strategy_name(self._db)
        with RadioSet(id="strategy-radio"):
            yield RadioButton(
                t("strategy.radio_official_label"),
                value=(active == "official"),
                id="radio-official",
            )
            yield RadioButton(
                t("strategy.radio_user_label"),
                value=(active == "user"),
                id="radio-user",
            )
        with Horizontal(classes="starter-row", id="starter-row"):
            yield Button(t("strategy.starter_blank_button"), id="btn-blank")
            yield Button(
                t("strategy.starter_copy_official_button"),
                id="btn-copy-official",
            )
        yield TextArea("", id="strategy-textarea")
        yield Markdown("", id="strategy-readonly")
        with Horizontal(classes="button-row"):
            yield Button(
                t("strategy.save_button"), id="btn-save", variant="primary"
            )
            yield Button(t("strategy.discard_button"), id="btn-discard")

    def on_mount(self) -> None:
        self._refresh_layout()
        # Re-enable radio event handling now that initial mount-time Changed
        # signals have fired.
        self._suppress_radio_event = False

    def _refresh_layout(self) -> None:
        """Sync the textarea / markdown / starter-row visibility to active mode."""
        active = get_active_strategy_name(self._db)
        ta = self.query_one("#strategy-textarea", TextArea)
        ro = self.query_one("#strategy-readonly", Markdown)
        starter = self.query_one("#starter-row", Horizontal)

        if active == "official":
            ta.display = False
            ro.display = True
            ro.update(load_official_strategy())
            starter.display = False
        else:  # user
            user_text = get_user_strategy_text(self._db)
            ta.display = True
            ro.display = False
            ta.text = user_text
            starter.display = (user_text == "")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if self._suppress_radio_event:
            return
        if event.pressed.id == "radio-official":
            self.action_select_official()
        elif event.pressed.id == "radio-user":
            self.action_select_user()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-blank":
            ta = self.query_one("#strategy-textarea", TextArea)
            ta.text = ""
            ta.focus()
            self._dirty = True
            self.query_one("#starter-row", Horizontal).display = False
        elif event.button.id == "btn-copy-official":
            ta = self.query_one("#strategy-textarea", TextArea)
            ta.text = load_official_strategy()
            ta.focus()
            self._dirty = True
            self.query_one("#starter-row", Horizontal).display = False
        elif event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-discard":
            self._refresh_layout()
            self._dirty = False

    def action_select_official(self) -> None:
        set_active_strategy(self._db, "official")
        self._refresh_layout()
        # tests may invoke this without a running App pilot — suppress
        # AttributeError / NoActiveAppError so action methods stay callable
        # outside the full Textual mount stack.
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_official"),
                severity="information",
                timeout=3,
            )

    def action_select_user(self) -> None:
        set_active_strategy(self._db, "user")
        self._refresh_layout()
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_user"),
                severity="information",
                timeout=3,
            )

    def action_save(self) -> None:
        active = get_active_strategy_name(self._db)
        if active != "user":
            return
        ta = self.query_one("#strategy-textarea", TextArea)
        save_user_strategy(self._db, ta.text)
        self._dirty = False
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_saved"),
                severity="information",
                timeout=2,
            )
