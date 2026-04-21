"""v0.8.0 Opt-A2: QuickAmountRow atom."""
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from scanner.tui.widgets.quick_amount_row import QuickAmountRow


class _Harness(App):
    def __init__(self, row: QuickAmountRow):
        super().__init__()
        self._row = row
        self.events = []

    def compose(self) -> ComposeResult:
        yield self._row

    def on_quick_amount_row_selected(self, event: QuickAmountRow.Selected) -> None:
        self.events.append(event.amount)


async def test_numeric_amounts_labeled_with_unit_prefix():
    row = QuickAmountRow(amounts=[10, 20, 50])
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        buttons = list(row.query(Button))
        assert len(buttons) == 3
        labels = {str(b.label) for b in buttons}
        assert labels == {"$10", "$20", "$50"}


async def test_custom_unit_prefix():
    row = QuickAmountRow(amounts=[10], unit="¥")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        button = row.query_one(Button)
        assert str(button.label) == "¥10"


async def test_string_amount_passes_through_literally():
    """String tokens like '全部' / 'all' render as-is (no unit prefix)."""
    row = QuickAmountRow(amounts=[20, 50, "全部"])
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        labels = {str(b.label) for b in row.query(Button)}
        assert labels == {"$20", "$50", "全部"}


async def test_numeric_button_press_emits_selected_with_int():
    row = QuickAmountRow(amounts=[10, 20, 50])
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#quick-20")
        await pilot.pause()
        assert app.events == [20]


async def test_string_button_press_emits_selected_with_str():
    """Non-ASCII tokens get positional ids (quick-tok-<idx>); the original
    token still flows through on Selected.amount."""
    row = QuickAmountRow(amounts=[20, "全部"])
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#quick-tok-1")
        await pilot.pause()
        assert app.events == ["全部"]


async def test_ascii_string_token_keeps_literal_id():
    """ASCII tokens like 'all' stay in the literal id (no positional fallback)."""
    row = QuickAmountRow(amounts=[20, "all"])
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#quick-all")
        await pilot.pause()
        assert app.events == ["all"]


async def test_button_ids_deterministic_from_amount():
    row = QuickAmountRow(amounts=[50, 100, 500])
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        ids = {b.id for b in row.query(Button)}
        assert ids == {"quick-50", "quick-100", "quick-500"}
