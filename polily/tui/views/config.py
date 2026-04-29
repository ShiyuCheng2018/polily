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
    """

    def __init__(self, section_id: str, title: str, *, icon: str = "") -> None:
        super().__init__()
        self.section_id = section_id
        self.section_title = title
        self.section_icon = icon

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self.section_icon}  {self.section_title}",
            classes="section-header",
        )
        # Leaf rows are mounted in T5.5 / T5.6; skeleton is empty for now.


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
            yield ConfigSection("movement", "异动触发 (Movement)", icon="●")
            yield ConfigSection("scoring", "评分 (Scoring)", icon="●")
            yield ConfigSection("mispricing", "错误定价 (Mispricing)", icon="●")
            yield ConfigSection("wallet", "钱包 (Wallet)", icon="●")

    def action_refresh(self) -> None:
        self.refresh(recompose=True)
