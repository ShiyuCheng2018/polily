"""v0.8.0 Opt-A3: BuySellActionRow atom."""
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from scanner.tui.widgets.buy_sell_action_row import BuySellActionRow


class _Harness(App):
    def __init__(self, row: BuySellActionRow):
        super().__init__()
        self._row = row
        self.events: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield self._row

    def on_buy_sell_action_row_pressed(self, event: BuySellActionRow.Pressed) -> None:
        self.events.append((event.outcome, event.side))


@pytest.mark.asyncio
async def test_buy_side_renders_two_buttons_labeled_买():  # noqa: N802 — intentional Chinese label in test name
    row = BuySellActionRow(side="buy")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        buttons = list(row.query(Button))
        assert len(buttons) == 2
        ids = {b.id for b in buttons}
        assert ids == {"btn-yes", "btn-no"}
        # Before update(), labels show verb + outcome with no price
        labels = [str(b.label) for b in buttons]
        assert any("买" in lbl and "YES" in lbl for lbl in labels)
        assert any("买" in lbl and "NO" in lbl for lbl in labels)


@pytest.mark.asyncio
async def test_sell_side_renders_卖_verb():  # noqa: N802 — intentional Chinese label in test name
    row = BuySellActionRow(side="sell")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        labels = [str(b.label) for b in row.query(Button)]
        assert any("卖" in lbl and "YES" in lbl for lbl in labels)
        assert any("卖" in lbl and "NO" in lbl for lbl in labels)


@pytest.mark.asyncio
async def test_invalid_side_raises():
    with pytest.raises(ValueError):
        BuySellActionRow(side="invalid")


@pytest.mark.asyncio
async def test_update_sets_price_in_labels():
    row = BuySellActionRow(side="buy")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=0.62, no_price=0.38)
        await pilot.pause()
        yes_btn = row.query_one("#btn-yes", Button)
        no_btn = row.query_one("#btn-no", Button)
        assert "62.0¢" in str(yes_btn.label)
        assert "38.0¢" in str(no_btn.label)


@pytest.mark.asyncio
async def test_update_missing_price_shows_price_unavailable():
    row = BuySellActionRow(side="buy")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=None, no_price=0.38)
        await pilot.pause()
        yes_btn = row.query_one("#btn-yes", Button)
        no_btn = row.query_one("#btn-no", Button)
        assert "不可用" in str(yes_btn.label)
        assert "38.0¢" in str(no_btn.label)
        # Missing-price button is disabled
        assert yes_btn.disabled
        assert not no_btn.disabled


@pytest.mark.asyncio
async def test_update_disabled_flag_overrides():
    """Sell context: button can be disabled even when price exists (e.g. no position)."""
    row = BuySellActionRow(side="sell")
    async with _Harness(row).run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=0.62, no_price=0.38, yes_disabled=True)
        await pilot.pause()
        yes_btn = row.query_one("#btn-yes", Button)
        no_btn = row.query_one("#btn-no", Button)
        assert yes_btn.disabled  # manually disabled despite price
        assert not no_btn.disabled


@pytest.mark.asyncio
async def test_yes_press_emits_pressed_with_yes_outcome():
    row = BuySellActionRow(side="buy")
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=0.62, no_price=0.38)
        await pilot.pause()
        await pilot.click("#btn-yes")
        await pilot.pause()
        assert ("yes", "buy") in app.events


@pytest.mark.asyncio
async def test_no_press_emits_pressed_with_no_outcome():
    row = BuySellActionRow(side="sell")
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=0.62, no_price=0.38)
        await pilot.pause()
        await pilot.click("#btn-no")
        await pilot.pause()
        assert ("no", "sell") in app.events


@pytest.mark.asyncio
async def test_disabled_button_does_not_emit_pressed():
    row = BuySellActionRow(side="sell")
    app = _Harness(row)
    async with app.run_test() as pilot:
        await pilot.pause()
        row.update(yes_price=0.62, no_price=0.38, yes_disabled=True)
        await pilot.pause()
        # Clicking a disabled button should not emit
        await pilot.click("#btn-yes")
        await pilot.pause()
        assert ("yes", "sell") not in app.events
