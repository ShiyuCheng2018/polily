"""v0.8.0 Opt-A1: ConfirmCancelBar atom."""
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from scanner.tui.widgets.confirm_cancel_bar import ConfirmCancelBar


class _Harness(App):
    def __init__(self, bar: ConfirmCancelBar):
        super().__init__()
        self._bar = bar
        self.messages = []

    def compose(self) -> ComposeResult:
        yield self._bar

    def on_confirm_cancel_bar_confirmed(self, event: ConfirmCancelBar.Confirmed) -> None:
        self.messages.append("confirmed")

    def on_confirm_cancel_bar_cancelled(self, event: ConfirmCancelBar.Cancelled) -> None:
        self.messages.append("cancelled")


async def test_default_labels_and_variants():
    bar = ConfirmCancelBar()
    app = _Harness(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        buttons = list(bar.query(Button))
        assert len(buttons) == 2
        labels = {str(b.label) for b in buttons}
        assert labels == {"确认", "取消"}
        ids = {b.id for b in buttons}
        assert ids == {"confirm", "cancel"}
        confirm = next(b for b in buttons if b.id == "confirm")
        assert confirm.variant == "primary"


async def test_custom_labels():
    bar = ConfirmCancelBar(confirm_label="确认取消", cancel_label="继续")
    app = _Harness(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        labels = {str(b.label) for b in bar.query(Button)}
        assert labels == {"确认取消", "继续"}


async def test_destructive_variant_uses_error_style():
    bar = ConfirmCancelBar(destructive=True)
    app = _Harness(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        confirm = next(b for b in bar.query(Button) if b.id == "confirm")
        assert confirm.variant == "error"


async def test_confirm_press_emits_confirmed_message():
    bar = ConfirmCancelBar()
    app = _Harness(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert "confirmed" in app.messages
        assert "cancelled" not in app.messages


async def test_cancel_press_emits_cancelled_message():
    bar = ConfirmCancelBar()
    app = _Harness(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert "cancelled" in app.messages
        assert "confirmed" not in app.messages
