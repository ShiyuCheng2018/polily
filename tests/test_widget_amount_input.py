"""v0.8.0 Opt-B2: AmountInput atom — numeric Input with validation.

Textual ``Input`` runs reactive setup that touches ``self.app`` during
``__init__``, so we build the widget inside ``compose`` where the App
context is active (same pattern as test_widget_field_row.py).
"""
from typing import Callable

from textual.app import App, ComposeResult
from textual.widgets import Input

from scanner.tui.widgets.amount_input import AmountInput


class _Harness(App):
    """Build AmountInput inside compose for active App context."""

    def __init__(self, build: Callable[[], AmountInput]) -> None:
        super().__init__()
        self._build = build
        self._input: AmountInput | None = None
        self.events: list[tuple] = []

    def compose(self) -> ComposeResult:
        self._input = self._build()
        yield self._input

    def on_amount_input_amount_changed(
        self, event: AmountInput.AmountChanged,
    ) -> None:
        self.events.append((event.value, event.valid, event.reason))


async def test_initial_empty_value_parses_invalid_empty():
    app = _Harness(lambda: AmountInput(id="amt"))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert v is None
        assert valid is False
        assert reason == "empty"


async def test_valid_positive_value_parses():
    app = _Harness(lambda: AmountInput(id="amt", value="12.5"))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert v == 12.5
        assert valid is True
        assert reason == "ok"


async def test_non_numeric_rejected():
    app = _Harness(lambda: AmountInput(id="amt", value="abc"))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert v is None
        assert valid is False
        assert reason == "not_numeric"


async def test_zero_or_negative_rejected():
    app = _Harness(lambda: AmountInput(id="amt", value="0"))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert v == 0.0
        assert valid is False
        assert reason == "negative"


async def test_below_min_rejected():
    app = _Harness(lambda: AmountInput(id="amt", value="5", min_value=10.0))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert valid is False
        assert reason == "below_min"


async def test_above_max_rejected():
    app = _Harness(lambda: AmountInput(id="amt", value="200", max_value=100.0))
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert valid is False
        assert reason == "above_max"


async def test_within_bounds_valid():
    app = _Harness(
        lambda: AmountInput(id="amt", value="50", min_value=10.0, max_value=100.0),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        v, valid, reason = app._input.parse()
        assert v == 50.0
        assert valid is True


async def test_set_bounds_triggers_re_evaluation():
    app = _Harness(lambda: AmountInput(id="amt", value="100"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.events.clear()
        app._input.set_bounds(max_value=50.0)  # now 100 > 50
        await pilot.pause()
        # Emitted an invalid AmountChanged event under the new bound.
        assert any(not v for _, v, _ in app.events)


async def test_input_change_emits_amount_changed_with_new_value():
    app = _Harness(lambda: AmountInput(id="amt", value=""))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.events.clear()
        # Simulate user typing.
        app._input.value = "25.5"
        await pilot.pause()
        # Should have emitted a valid AmountChanged with 25.5.
        assert any(val == 25.5 and valid for val, valid, _ in app.events)


async def test_is_a_textual_input():
    """AmountInput inherits from Input — query_one(..., Input) still finds it."""
    app = _Harness(lambda: AmountInput(id="amt", value="10"))
    async with app.run_test() as pilot:
        await pilot.pause()
        found = app._input.screen.query_one("#amt", Input)
        assert found is app._input
        assert isinstance(found, Input)
