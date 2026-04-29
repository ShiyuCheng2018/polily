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
        max-height: 28;
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
    BINDINGS = [Binding("escape", "cancel", "取消")]

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
