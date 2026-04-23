# tests/test_widget_polily_card.py
"""v0.8.0 Task 5: PolilyCard atom widget — tighter-padded card variant."""
from textual.app import App, ComposeResult
from textual.widgets import Static

from polily.tui.widgets.polily_card import PolilyCard


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


async def test_polily_card_title_is_first_child_when_composed_with_context_manager():
    """Regression: `with PolilyCard(title=...):` used to put title LAST
    (same bug PolilyZone had — fixed via on_mount mount at index 0).
    """
    class _H(App):
        def compose(self) -> ComposeResult:
            with PolilyCard(title="钱包余额"):
                yield Static("child-a", id="child-a")
                yield Static("child-b", id="child-b")

    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(PolilyCard)
        children = list(card.children)
        assert len(children) == 3, f"expected 3 children (title + 2), got {len(children)}"
        assert "polily-card-title" in children[0].classes, \
            f"first child is not title; got classes {children[0].classes}"
        assert children[1].id == "child-a"
        assert children[2].id == "child-b"
