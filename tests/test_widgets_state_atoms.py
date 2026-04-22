"""v0.8.0 Task 8: EmptyState / LoadingState / SectionHeader."""
from textual.app import App, ComposeResult

from polily.tui.widgets.empty_state import EmptyState
from polily.tui.widgets.loading_state import LoadingState
from polily.tui.widgets.section_header import SectionHeader


class _Harness(App):
    def __init__(self, widget):
        super().__init__()
        self._w = widget
    def compose(self) -> ComposeResult:
        yield self._w


async def test_empty_state_renders_icon_and_message():
    w = EmptyState(icon="\uf002", message="暂无记录")
    async with _Harness(w).run_test() as pilot:
        await pilot.pause()
        r = str(w.render())
        assert "\uf002" in r and "暂无记录" in r


async def test_loading_state_renders_spinner_and_message():
    w = LoadingState(message="加载中")
    async with _Harness(w).run_test() as pilot:
        await pilot.pause()
        assert "加载中" in str(w.render())


async def test_section_header_renders_title_and_icon():
    w = SectionHeader(title="分析队列", icon="\uf017")
    async with _Harness(w).run_test() as pilot:
        await pilot.pause()
        r = str(w.render())
        assert "分析队列" in r and "\uf017" in r
