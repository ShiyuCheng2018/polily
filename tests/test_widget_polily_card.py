# tests/test_widget_polily_card.py
"""v0.8.0 Task 5: PolilyCard atom widget — tighter-padded card variant."""
from textual.app import App, ComposeResult

from scanner.tui.widgets.polily_card import PolilyCard


class _Harness(App):
    def __init__(self, card: PolilyCard):
        super().__init__()
        self._card = card
    def compose(self) -> ComposeResult:
        yield self._card


async def test_polily_card_renders_with_title():
    card = PolilyCard(title="钱包余额")
    harness = _Harness(card)
    async with harness.run_test() as pilot:
        await pilot.pause()
        title = card.query_one(".polily-card-title")
        assert "钱包余额" in str(title.render())


async def test_polily_card_has_card_class():
    card = PolilyCard(title="T")
    harness = _Harness(card)
    async with harness.run_test() as pilot:
        await pilot.pause()
        assert "polily-card" in card.classes
