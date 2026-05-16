"""Sidebar must expose `config` menu item between archive and changelog."""
from polily.tui.icons import ICON_CONFIG
from polily.tui.widgets.sidebar import MENU_ICONS, Sidebar, SidebarItem


def test_menu_icons_includes_config():
    assert MENU_ICONS["config"] == ICON_CONFIG


def test_compose_emits_config_item_in_correct_order():
    """config sits between archive and strategy (per design §5.1; v0.12.0+ adds strategy before changelog)."""
    sidebar = Sidebar()
    items = [item for item in sidebar.compose() if isinstance(item, SidebarItem)]
    menu_ids = [item.menu_id for item in items]
    assert menu_ids == [
        "tasks", "monitor", "paper", "wallet",
        "history", "archive", "config", "strategy", "changelog",
    ]
