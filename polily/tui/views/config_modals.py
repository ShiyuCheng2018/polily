"""ConfigEditModal: edit a single config knob.

Per design §5.3. 3-tier validation:
  - live: field-level (modal-internal, on every keystroke) — T6.2
  - save-time: full PolilyConfig validation (this modal) — T6.3
  - startup: fatal screen — Phase 7

EPHEMERAL_FIELDS / HIDDEN_IN_TUI keys are filtered out at the
ConfigView level (LeafRow whitelist) so this modal trusts that
key_path is editable. The constructor still rejects non-territory-A
keys as defense-in-depth (T6.7).
"""
from __future__ import annotations

import contextlib
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static

from polily.tui.icons import ICON_CONFIG
from polily.tui.widgets.confirm_cancel_bar import ConfirmCancelBar
from polily.tui.widgets.field_row import FieldRow
from polily.tui.widgets.polily_card import PolilyCard

_MODAL_WIDTH = 80


class ConfigEditModal(ModalScreen[bool | None]):
    """Modal returns True on successful save, False on reset, None on cancel."""

    DEFAULT_CSS = f"""
    ConfigEditModal {{
        align: center middle;
    }}
    ConfigEditModal #dialog-box {{
        width: {_MODAL_WIDTH};
        height: auto;
        max-height: 32;
    }}
    ConfigEditModal #dialog-box > PolilyCard {{
        height: auto;
        margin: 0;
    }}
    ConfigEditModal #modal-keypath {{
        color: $text-muted;
        padding: 0 0 1 0;
    }}
    ConfigEditModal #modal-description {{
        height: auto;
        max-height: 12;
        overflow-y: auto;
    }}
    ConfigEditModal #modal-input {{ width: 30; }}
    ConfigEditModal #modal-error {{
        color: $error;
        padding: 0 0 1 0;
    }}
    ConfigEditModal ConfirmCancelBar Button {{ min-width: 14; }}
    ConfigEditModal #reset-btn {{
        background: $warning 30%;
        min-width: 14;
    }}
    """
    # priority=True: Input widget at #modal-input takes focus on mount and would
    # otherwise consume the escape key before the screen-level binding fires.
    # priority bindings run BEFORE focused-widget key handling, so ESC reliably
    # dismisses regardless of which child has focus.
    BINDINGS = [Binding("escape", "cancel", "取消", priority=True)]

    def __init__(
        self,
        *,
        service,
        key_path: str,
        current_value: Any,
        default_value: Any,
    ) -> None:
        # T6.7 — defense-in-depth: reject HIDDEN_IN_TUI / EPHEMERAL paths
        # at construction. UI level (LeafRow whitelist in ConfigView) already
        # prevents these from rendering, so this is belt-and-suspenders.
        from polily.core.config_store import is_territory_a
        if not is_territory_a(key_path):
            raise ValueError(
                f"{key_path} is not editable (HIDDEN_IN_TUI or EPHEMERAL)"
            )
        super().__init__()
        self._service = service
        self._key_path = key_path
        self._current_value = current_value
        self._default_value = default_value

    @property
    def _last_segment(self) -> str:
        return self._key_path.rsplit(".", 1)[-1]

    def compose(self) -> ComposeResult:
        from polily.core.config_docs import load_all
        docs = load_all()
        description_md = docs.get(
            self._key_path,
            f"*(no markdown description for `{self._key_path}`)*",
        )

        with Vertical(id="dialog-box"):
            with PolilyCard(title=f"{ICON_CONFIG} 编辑 · {self._last_segment}"):
                yield Static(
                    f"key_path: [bold]{self._key_path}[/bold]",
                    id="modal-keypath",
                )
                yield Markdown(description_md, id="modal-description")
                yield FieldRow(
                    label="新值",
                    unit="",
                    input_widget=Input(
                        value=str(self._current_value), id="modal-input",
                    ),
                )
                yield Static("", id="modal-error")
                yield Static(
                    "[yellow]⚠ 保存后需要重启 polily 才生效[/yellow]",
                    id="modal-warn",
                )
                yield ConfirmCancelBar(
                    confirm_label="保存（需重启）",
                    cancel_label="取消",
                )
                yield Button("重置为默认", id="reset-btn", variant="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_confirm_cancel_bar_cancelled(
        self, event: ConfirmCancelBar.Cancelled,
    ) -> None:
        self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "modal-input":
            return
        from polily.core.config import _coerce_value, _resolve_field_annotation
        annotation = _resolve_field_annotation(self._key_path)
        if annotation is None:
            self._show_error(f"无法定位 {self._key_path} 的类型")
            return
        try:
            _coerce_value(event.value, annotation)
        except ValueError as e:
            self._show_error(str(e))
            return
        self._show_error("")

    def _show_error(self, message: str) -> None:
        # Pydantic ValidationError messages contain `[type=...]` brackets that
        # Static.update() interprets as Rich markup → MarkupError. Escape to
        # render literally (T6.3).
        from rich.markup import escape as _escape_markup
        safe = _escape_markup(message) if message else ""
        with contextlib.suppress(Exception):
            self.query_one("#modal-error", Static).update(safe)
        with contextlib.suppress(Exception):
            self.query_one("#confirm", Button).disabled = bool(message)

    def on_confirm_cancel_bar_confirmed(
        self, event: ConfirmCancelBar.Confirmed,
    ) -> None:
        self._do_save()

    def _do_save(self) -> None:
        from polily.core.config import (
            ConfigValidationError,
            _coerce_value,
            _resolve_field_annotation,
            save_knob,
        )
        raw = self.query_one("#modal-input", Input).value
        annotation = _resolve_field_annotation(self._key_path)
        try:
            new_value = _coerce_value(raw, annotation)
        except ValueError as e:
            self._show_error(str(e))
            return
        try:
            save_knob(self._service.db, self._key_path, new_value)
        except ConfigValidationError as e:
            self._show_error(f"Pydantic 校验失败: {e}")
            return
        self.notify(f"已保存 {self._key_path} = {new_value}")
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reset-btn":
            self._do_reset()

    def _do_reset(self) -> None:
        from polily.core.config_store import reset
        try:
            reset(self._service.db, self._key_path)
        except Exception as e:
            self._show_error(f"重置失败: {e}")
            return
        # Update the input + cleared current_value tracking
        self.query_one("#modal-input", Input).value = str(self._default_value)
        self._current_value = self._default_value
        self._show_error("")
        # SF5 — defensive explicit re-enable. User flow that requires this:
        # type invalid → live validation disables Save → click Reset →
        # without this line, if `_show_error("")`'s `contextlib.suppress`
        # swallowed any exception (e.g., during a fast-firing input change
        # event), the disabled flag would stay True and the user couldn't
        # save the default. Belt-and-suspenders.
        with contextlib.suppress(Exception):
            self.query_one("#confirm", Button).disabled = False
        self.notify(f"已重置 {self._last_segment} 为默认 {self._default_value}")
