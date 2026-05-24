"""Strategy page — official (read-only) vs user (view ↔ edit) state machine.

v0.12.0 shipped a single-slot user strategy editor with the user mode hard-
wired to "edit" (TextArea always visible). v0.12.3 splits user mode into
two states for typical document-editor UX:

  official      → Markdown render of packaged default.md (read-only).
  user_view     → Markdown render of stored user_strategy + [Edit] button.
                  Default state when entering user mode with non-empty text.
  user_edit     → TextArea + [Save] [Cancel] (+ starter row when empty).
                  Entered explicitly via [Edit] button, or as the only
                  available state when user_strategy is empty.

Why the split:
- Bug fix #1: previously user mode showed raw markdown text in TextArea —
  the user's own strategy never got Markdown-rendered. user_view solves
  that.
- Bug fix #2: previously every visit to user mode was "edit mode" with
  Save/Cancel buttons regardless of whether the user wanted to edit.
  Typical doc-editor UX is view-by-default, edit-on-explicit-action.

Confirm-discard modal:
- Triggered when leaving user_edit with unsaved changes (Cancel button OR
  radio toggle to official). The `strategy.unsaved_warning` i18n key has
  existed since v0.12.0 but wasn't wired up before this slice — now it is.

Hot-swap of active_strategy still takes effect on next analysis dispatch.
"""
from __future__ import annotations

import contextlib
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, RadioButton, RadioSet, Static, TextArea

from polily.core.db import PolilyDB
from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
from polily.core.strategy_store import (
    get_active_strategy_name,
    get_user_strategy_text,
    load_official_strategy,
    save_user_strategy,
    set_active_strategy,
)
from polily.tui.i18n import t

ViewMode = Literal["official", "user_view", "user_edit"]


class _DiscardConfirmModal(ModalScreen[bool]):
    """Yes/no modal asking the user whether to discard unsaved edits.

    Returns True when the user confirms discard, False when they choose to
    keep editing. Used by StrategyView before any mode transition that
    would otherwise silently drop in-progress changes.

    Kept inline (rather than in a shared modal module) because it's tightly
    coupled to StrategyView's lifecycle and not reused elsewhere yet.
    """

    DEFAULT_CSS = """
    _DiscardConfirmModal {
        align: center middle;
    }
    _DiscardConfirmModal #dialog-box {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }
    _DiscardConfirmModal Static {
        margin-bottom: 1;
    }
    _DiscardConfirmModal #button-row {
        height: 3;
        align: center middle;
    }
    _DiscardConfirmModal #button-row Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static(t("strategy.unsaved_warning"))
            with Horizontal(id="button-row"):
                yield Button(
                    t("strategy.unsaved_confirm_discard"),
                    id="btn-confirm-discard",
                    variant="error",
                )
                yield Button(
                    t("strategy.unsaved_confirm_keep"),
                    id="btn-keep-editing",
                    variant="primary",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm-discard")


class StrategyView(Vertical):
    """v0.12.3 Strategy page — 3-mode state machine (official / user_view / user_edit).

    Layout (top → bottom):
      RadioSet              (sticky, height auto)
      Horizontal starter    (sticky, height auto, only in user_edit + empty text)
      VerticalScroll(Markdown)  (1fr, only in official OR user_view)
      TextArea              (1fr, only in user_edit)
      Horizontal buttons    (sticky, height 3, contents vary by mode)

    The single Markdown widget serves both `official` and `user_view` —
    content is swapped in `_apply_mode()`. This avoids double-mounting
    a near-duplicate widget pair.
    """

    BINDINGS = [
        ("ctrl+s", "save", t("strategy.save_button")),
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
    StrategyView TextArea, StrategyView #strategy-readonly-scroll {
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
        self._mode: ViewMode = "official"
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
        with VerticalScroll(id="strategy-readonly-scroll"):
            yield Markdown("", id="strategy-readonly")
        with Horizontal(classes="button-row"):
            yield Button(t("strategy.edit_button"), id="btn-edit", variant="primary")
            yield Button(
                t("strategy.save_button"), id="btn-save", variant="primary"
            )
            yield Button(t("strategy.discard_button"), id="btn-discard")

    def on_mount(self) -> None:
        self._apply_mode(self._compute_initial_mode())
        self._suppress_radio_event = False
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        with contextlib.suppress(Exception):
            get_event_bus().unsubscribe(
                TOPIC_LANGUAGE_CHANGED, self._on_lang_changed,
            )

    def _on_lang_changed(self, payload: dict) -> None:
        """Re-apply t() to every static label after a language switch."""
        with contextlib.suppress(Exception):
            self.query_one("#radio-official", RadioButton).label = t(
                "strategy.radio_official_label",
            )
            self.query_one("#radio-user", RadioButton).label = t(
                "strategy.radio_user_label",
            )
            self.query_one("#btn-blank", Button).label = t(
                "strategy.starter_blank_button",
            )
            self.query_one("#btn-copy-official", Button).label = t(
                "strategy.starter_copy_official_button",
            )
            self.query_one("#btn-edit", Button).label = t("strategy.edit_button")
            self.query_one("#btn-save", Button).label = t("strategy.save_button")
            self.query_one("#btn-discard", Button).label = t(
                "strategy.discard_button",
            )

    # ------------------------------------------------------------------
    # Mode computation + application
    # ------------------------------------------------------------------

    def _compute_initial_mode(self) -> ViewMode:
        """Derive the initial display mode from active_strategy + user_text.

        Called once on mount and after each radio toggle. The user mode
        decision rule:
        - non-empty user text → user_view (read-only render with [Edit])
        - empty user text     → user_edit (TextArea + starter buttons)
                                (because there's nothing to view)
        """
        active = get_active_strategy_name(self._db)
        if active == "official":
            return "official"
        user_text = get_user_strategy_text(self._db)
        return "user_view" if user_text else "user_edit"

    def _apply_mode(self, mode: ViewMode) -> None:
        """Show/hide widgets + populate content per the requested mode.

        Centralized so transitions never get out of sync with widget
        visibility. The single Markdown widget serves both official and
        user_view — content swap happens here.
        """
        self._mode = mode
        ta = self.query_one("#strategy-textarea", TextArea)
        md = self.query_one("#strategy-readonly", Markdown)
        ro_scroll = self.query_one("#strategy-readonly-scroll", VerticalScroll)
        starter = self.query_one("#starter-row", Horizontal)
        btn_edit = self.query_one("#btn-edit", Button)
        btn_save = self.query_one("#btn-save", Button)
        btn_discard = self.query_one("#btn-discard", Button)

        if mode == "official":
            ta.display = False
            ro_scroll.display = True
            md.update(load_official_strategy())
            ro_scroll.scroll_home(animate=False)
            starter.display = False
            btn_edit.display = False
            btn_save.display = False
            btn_discard.display = False
        elif mode == "user_view":
            ta.display = False
            ro_scroll.display = True
            md.update(get_user_strategy_text(self._db))
            ro_scroll.scroll_home(animate=False)
            starter.display = False
            btn_edit.display = True
            btn_save.display = False
            btn_discard.display = False
        else:  # user_edit
            user_text = get_user_strategy_text(self._db)
            ta.display = True
            ro_scroll.display = False
            # Refill textarea from the saved value each time we enter
            # edit mode. (Preserving in-flight edits across mode changes
            # would require a separate "current edit buffer" attribute —
            # not worth the complexity given how rarely users toggle.)
            ta.text = user_text
            starter.display = (user_text == "")
            btn_edit.display = False
            btn_save.display = True
            btn_discard.display = True

    # ------------------------------------------------------------------
    # Dirty detection
    # ------------------------------------------------------------------

    def _is_dirty(self) -> bool:
        """True iff the textarea content differs from the saved user_strategy.

        Computed on demand (no real-time tracking of TextArea.Changed). Used
        when about to leave user_edit — radio toggle or Cancel button. If
        dirty, we push the confirm modal; if clean, the transition is
        immediate.
        """
        if self._mode != "user_edit":
            return False
        ta = self.query_one("#strategy-textarea", TextArea)
        return ta.text != get_user_strategy_text(self._db)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if self._suppress_radio_event:
            return
        target = "official" if event.pressed.id == "radio-official" else "user"
        # If user is mid-edit with unsaved changes, intercept and ask first.
        if self._is_dirty():
            self._confirm_then(
                lambda: self._do_radio_switch(target),
                lambda: self._revert_radio_visual(),
            )
            return
        self._do_radio_switch(target)

    def _do_radio_switch(self, target: str) -> None:
        """Apply the radio switch unconditionally (caller has cleared dirty check)."""
        if target == "official":
            self.action_select_official()
        else:
            self.action_select_user()

    def _revert_radio_visual(self) -> None:
        """Undo the visual radio toggle if user chose to keep editing.

        Textual's RadioSet flips the selected button BEFORE firing Changed,
        so a "keep editing" choice has to flip it back. We suppress the
        re-fire to avoid recursion.
        """
        self._suppress_radio_event = True
        try:
            target_id = (
                "radio-user" if self._mode in ("user_view", "user_edit")
                else "radio-official"
            )
            self.query_one(f"#{target_id}", RadioButton).value = True
        finally:
            self._suppress_radio_event = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-edit":
            # user_view → user_edit (no dirty check; we're entering edit,
            # not leaving it)
            self._apply_mode("user_edit")
            with contextlib.suppress(Exception):
                self.query_one("#strategy-textarea", TextArea).focus()
        elif event.button.id == "btn-blank":
            ta = self.query_one("#strategy-textarea", TextArea)
            ta.text = ""
            ta.focus()
            self.query_one("#starter-row", Horizontal).display = False
        elif event.button.id == "btn-copy-official":
            ta = self.query_one("#strategy-textarea", TextArea)
            ta.text = load_official_strategy()
            ta.focus()
            self.query_one("#starter-row", Horizontal).display = False
        elif event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-discard":
            self._cancel_edit()

    # ------------------------------------------------------------------
    # Action methods (test-callable, no UI dependency)
    # ------------------------------------------------------------------

    def action_select_official(self) -> None:
        set_active_strategy(self._db, "official")
        self._apply_mode("official")
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_official"),
                severity="information",
                timeout=3,
            )

    def action_select_user(self) -> None:
        set_active_strategy(self._db, "user")
        self._apply_mode(
            "user_view" if get_user_strategy_text(self._db) else "user_edit"
        )
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_user"),
                severity="information",
                timeout=3,
            )

    def action_enter_edit(self) -> None:
        """Public action to enter edit mode from user_view.

        Exposed so tests (and future keyboard shortcuts) can drive the
        transition without going through the Button.Pressed event.
        """
        if self._mode == "user_view":
            self._apply_mode("user_edit")

    def action_save(self) -> None:
        # Only meaningful in user_edit. From user_view there's nothing to
        # save (Ctrl+S in view mode is a no-op rather than an error).
        if self._mode != "user_edit":
            return
        ta = self.query_one("#strategy-textarea", TextArea)
        save_user_strategy(self._db, ta.text)
        # After save, drop back to view (or stay in edit-empty if the
        # saved content was empty — edge case but consistent).
        next_mode: ViewMode = "user_view" if ta.text else "user_edit"
        self._apply_mode(next_mode)
        with contextlib.suppress(Exception):
            self.app.notify(
                t("strategy.save_toast_saved"),
                severity="information",
                timeout=2,
            )

    def _cancel_edit(self) -> None:
        """Cancel button handler.

        - If clean: leave edit immediately.
        - If dirty: push confirm modal; only leave on confirmed discard.
        """
        if self._is_dirty():
            self._confirm_then(
                lambda: self._do_exit_edit(),
                lambda: None,  # keep editing
            )
        else:
            self._do_exit_edit()

    def _do_exit_edit(self) -> None:
        """Leave edit mode → land in user_view if there's content, else
        re-enter user_edit (empty starter state).
        """
        if get_user_strategy_text(self._db):
            self._apply_mode("user_view")
        else:
            # No saved content to return to — re-render edit with empty
            # textarea + starter row.
            self._apply_mode("user_edit")

    # ------------------------------------------------------------------
    # Confirm modal helper
    # ------------------------------------------------------------------

    def _confirm_then(self, on_discard, on_keep) -> None:
        """Push the discard-confirm modal; route the result.

        Wrapped in suppress because tests sometimes call mode-transition
        actions outside a full App pilot, where push_screen isn't
        available — fall through to on_discard so test flows still work.
        """
        try:
            self.app.push_screen(
                _DiscardConfirmModal(),
                lambda confirmed: on_discard() if confirmed else on_keep(),
            )
        except Exception:
            # No app context (test environment etc) — default to discard
            # so the transition still completes.
            on_discard()
