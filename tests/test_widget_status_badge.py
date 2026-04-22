# tests/test_widget_status_badge.py
"""v0.8.0 Task 6: StatusBadge atom."""
from textual.app import App, ComposeResult

from polily.tui.widgets.status_badge import StatusBadge


class _Harness(App):
    def __init__(self, badge: StatusBadge):
        super().__init__()
        self._badge = badge
    def compose(self) -> ComposeResult:
        yield self._badge


async def test_status_badge_renders_icon_and_chinese_label():
    badge = StatusBadge(status="completed")
    harness = _Harness(badge)
    async with harness.run_test() as pilot:
        await pilot.pause()
        rendered = str(badge.render())
        assert "\uf00c" in rendered, "missing completed icon"
        assert "已完成" in rendered, "missing Chinese label"


async def test_status_badge_applies_semantic_color_class():
    badge = StatusBadge(status="failed")
    harness = _Harness(badge)
    async with harness.run_test() as pilot:
        await pilot.pause()
        assert "text-error" in badge.classes, "failed should use error color"
