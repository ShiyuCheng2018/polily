"""Sidebar: navigation menu with market counts.

v0.8.0 Task 32 migration:
- Each menu entry is prefixed with a Nerd Font glyph via the central
  ICON_* constants (requires a NF-patched terminal font; fallback tiles
  render as a blank box — acceptable degradation).
- Selected-state CSS uses `$primary` via theme variables — no hardcoded
  colors. Hover / active tint mirrors the PolilyZone / PolilyCard feel.
- Menu list order is preserved (see `MainScreen.MENU_ORDER`).
"""

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from polily.tui.icons import (
    ICON_AUTO_MONITOR,
    ICON_CHANGELOG,
    ICON_COMPLETED,
    ICON_EVENT,
    ICON_POSITION,
    ICON_SCAN,
    ICON_WALLET,
)


class MenuSelected(Message):
    """Sent when a sidebar menu item is selected."""
    def __init__(self, menu_id: str):
        super().__init__()
        self.menu_id = menu_id


# Menu id → Nerd Font glyph (v0.8.0).
MENU_ICONS: dict[str, str] = {
    "tasks": ICON_SCAN,
    "monitor": ICON_AUTO_MONITOR,
    "paper": ICON_POSITION,
    "wallet": ICON_WALLET,
    "history": ICON_COMPLETED,
    "archive": ICON_EVENT,
    "changelog": ICON_CHANGELOG,
}


class SidebarItem(Static):
    """A clickable sidebar menu item."""

    def __init__(self, label: str, menu_id: str, count: int = 0):
        super().__init__(label)
        self.menu_id = menu_id
        self.count = count
        self._label = label
        self._icon = MENU_ICONS.get(menu_id, "")
        self._has_new = False
        self._update_display()

    def _update_display(self):
        count_str = f" ({self.count})" if self.count > 0 else ""
        new_mark = " [bold yellow]*[/bold yellow]" if self._has_new else ""
        icon = f"{self._icon} " if self._icon else ""
        if self.has_class("-active"):
            self.update(f"[b]{icon}{self._label}{count_str}{new_mark}[/b]")
        else:
            self.update(f"{icon}{self._label}{count_str}{new_mark}")

    def set_count(self, count: int):
        self.count = count
        self._update_display()

    def set_active(self, active: bool):
        if active:
            self.add_class("-active")
        else:
            self.remove_class("-active")
        self._update_display()

    def mark_new(self, has_new: bool):
        self._has_new = has_new
        self._update_display()

    def on_click(self) -> None:
        self.post_message(MenuSelected(self.menu_id))


class Sidebar(Widget):
    """Left sidebar with navigation menu."""

    DEFAULT_CSS = """
    Sidebar {
        width: 22;
        dock: left;
        border-right: tall $primary;
        background: $surface;
    }
    Sidebar SidebarItem {
        height: 1;
        padding: 0 1;
        margin-bottom: 1;
        color: $text;
    }
    Sidebar SidebarItem:hover {
        background: $primary 20%;
        color: $text;
    }
    Sidebar SidebarItem.-active {
        background: $primary 15%;
        color: $primary;
        text-style: bold;
    }
    Sidebar .sidebar-title {
        color: $primary;
        text-style: bold;
        text-align: center;
        padding: 1 0;
    }
    Sidebar .sidebar-hint {
        color: $text-muted;
    }
    /* v0.8.0+: pin POLL status indicator to sidebar bottom via dock. */
    Sidebar #poll-indicator {
        dock: bottom;
        height: 2;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
    }
    """

    # Theme-colored via .sidebar-title (`color: $primary`) — auto-follows
    # polily-dark (blue) / polily-geek (phosphor green) / any built-in.

    def compose(self) -> ComposeResult:
        yield Static("[bold]POLILY[/bold]", classes="sidebar-title")
        yield Static("")
        yield SidebarItem("任务记录", "tasks")
        yield SidebarItem("监控列表", "monitor")
        yield SidebarItem("持仓", "paper")
        yield SidebarItem("钱包", "wallet")
        yield SidebarItem("历史", "history")
        yield SidebarItem("归档", "archive")
        yield SidebarItem("更新日志", "changelog")
        yield Static("  [dim]POLL[/dim] --", id="poll-indicator")

    def set_poll_status(self, alive: bool) -> None:
        """Update poll indicator: green dot if alive, dim dot if not.

        Note: rich markup in `Static.update` uses Rich's color names, not
        Textual theme variables — so we keep `green` / `dim` here. The
        surrounding chrome (sidebar background, title color) is fully
        theme-driven via DEFAULT_CSS above.
        """
        indicator = self.query_one("#poll-indicator", Static)
        if alive:
            indicator.update("  [green]●[/green] POLL")
        else:
            indicator.update("  [dim]○[/dim] [dim]POLL[/dim]")

    def update_counts(self, monitor: int, paper: int,
                       archive: int = 0, history: int = 0):
        for item in self.query(SidebarItem):
            if item.menu_id == "monitor":
                item.set_count(monitor)
            elif item.menu_id == "paper":
                item.set_count(paper)
            elif item.menu_id == "history":
                item.set_count(history)
            elif item.menu_id == "archive":
                item.set_count(archive)

    def set_active_menu(self, menu_id: str):
        for item in self.query(SidebarItem):
            item.set_active(item.menu_id == menu_id)

    def mark_new_data(self, menu_id: str):
        for item in self.query(SidebarItem):
            if item.menu_id == menu_id:
                item.mark_new(True)

    def clear_new_data(self, menu_id: str):
        for item in self.query(SidebarItem):
            if item.menu_id == menu_id:
                item.mark_new(False)
