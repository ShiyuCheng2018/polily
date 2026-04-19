"""Sidebar: navigation menu with market counts."""

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


class MenuSelected(Message):
    """Sent when a sidebar menu item is selected."""
    def __init__(self, menu_id: str):
        super().__init__()
        self.menu_id = menu_id


class SidebarItem(Static):
    """A clickable sidebar menu item."""

    def __init__(self, label: str, menu_id: str, count: int = 0):
        super().__init__(label)
        self.menu_id = menu_id
        self.count = count
        self._label = label
        self._has_new = False
        self._update_display()

    def _update_display(self):
        count_str = f" ({self.count})" if self.count > 0 else ""
        new_mark = " [bold yellow]*[/bold yellow]" if self._has_new else ""
        if self.has_class("-active"):
            self.update(f"▸ {self._label}{count_str}{new_mark}")
        else:
            self.update(f"  {self._label}{count_str}{new_mark}")

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
    }
    Sidebar SidebarItem {
        height: 1;
        padding: 0 1;
    }
    Sidebar SidebarItem:hover {
        background: $primary 20%;
    }
    Sidebar SidebarItem.-active {
        background: $primary 15%;
        color: $primary;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("  [bold]Polily[/bold]", classes="sidebar-title")
        yield Static("")
        yield SidebarItem("任务记录", "tasks")
        yield SidebarItem("监控列表", "monitor")
        yield SidebarItem("持仓", "paper")
        yield SidebarItem("钱包", "wallet")
        yield SidebarItem("历史", "history")
        yield SidebarItem("归档", "archive")
        yield Static("")
        yield Static("  [dim]快捷键[/dim]")
        yield Static("  [dim]0-5  切换视图[/dim]")
        yield Static("  [dim]r    刷新[/dim]")
        yield Static("  [dim]q    退出[/dim]")
        yield Static("")
        yield Static("  [dim]其他见底栏[/dim]")
        yield Static("")
        yield Static("  [dim]POLL[/dim] --", id="poll-indicator")

    def set_poll_status(self, alive: bool) -> None:
        """Update poll indicator: green dot if alive, dim dot if not."""
        indicator = self.query_one("#poll-indicator", Static)
        if alive:
            indicator.update("  [green]●[/] POLL")
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
