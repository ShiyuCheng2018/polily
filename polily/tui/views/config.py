"""ConfigView: sidebar entry "⚙ 配置" — TUI knob editor.

Per design §5.2 + Q7. Layout:
  - Banner at top (drift count + "重启 polily" button) — Phase 5.7
  - 4 sections (Movement / Scoring / Mispricing / Wallet), each foldable
  - Inside each section: 2-line leaf rows (last_segment / dim full key_path)
  - Movement section has a nested weights subtree (4 market types ×
    magnitude/quality × N signals)

Edit interaction (modal) is Phase 6.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from polily.tui.bindings import NAV_BINDINGS
from polily.tui.icons import ICON_CONFIG
from polily.tui.service import PolilyService
from polily.tui.widgets.polily_card import PolilyCard


class ConfigSection(Widget):
    """One foldable section. Holds a header + list of LeafRow children."""

    DEFAULT_CSS = """
    ConfigSection { height: auto; padding: 1 0; }
    ConfigSection .section-header { color: $primary; text-style: bold; padding: 0 1; }
    ConfigSection.collapsed .section-body { display: none; }
    """

    BINDINGS = [Binding("enter", "toggle", show=False)]

    def __init__(
        self,
        section_id: str,
        title: str,
        *,
        icon: str = "",
        expanded: bool = False,
    ) -> None:
        super().__init__()
        self.section_id = section_id
        self.section_title = title
        self.section_icon = icon
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        marker = "▼" if self.expanded else "▶"
        yield Static(
            f"{marker}  {self.section_title}",
            classes="section-header",
            id=f"header-{self.section_id}",
        )
        # Body is mounted-but-hidden when collapsed; fills with rows in T5.6.
        body_classes = "section-body"
        body = Widget(classes=body_classes, id=f"body-{self.section_id}")
        yield body

    def action_toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")
        self.refresh(recompose=True)


class ConfigView(Widget):
    """Top-level config view widget."""

    DEFAULT_CSS = """
    ConfigView { height: 1fr; padding: 1 2; }
    ConfigView #config-scroll { height: 1fr; }
    """

    BINDINGS = [
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    def __init__(self, service: PolilyService) -> None:
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield PolilyCard(
            title=f"{ICON_CONFIG} 配置",
            id="config-card",
        )
        with VerticalScroll(id="config-scroll"):
            yield ConfigSection("movement", "异动触发 (Movement)", expanded=True)
            yield ConfigSection("scoring", "评分 (Scoring)")
            yield ConfigSection("mispricing", "错误定价 (Mispricing)")
            yield ConfigSection("wallet", "钱包 (Wallet)")

    def action_refresh(self) -> None:
        self.refresh(recompose=True)
