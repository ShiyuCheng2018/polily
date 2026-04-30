"""FatalConfigScreen renders error message + reset hints."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from polily.tui.views._config_fatal_screen import FatalConfigScreen


class _Harness(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)

    def compose(self) -> ComposeResult:
        yield from ()


@pytest.mark.asyncio
async def test_fatal_screen_displays_validation_error_and_recovery_hints():
    err = "1 validation error for PolilyConfig\nwallet.starting_balance: ..."
    screen = FatalConfigScreen(error_message=err)
    async with _Harness(screen).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = "\n".join(
            str(w.render()) for w in screen.query("Static")
        )
        assert "配置损坏" in text
        assert "wallet.starting_balance" in text
        assert "polily config reset --all" in text


# ---- SF18: Pydantic ValidationError messages contain Rich markup ----------


@pytest.mark.asyncio
async def test_fatal_screen_handles_pydantic_bracket_markup():
    """SF18 — Pydantic ValidationError messages contain `[type=...]` bracket
    syntax that Rich tries to interpret as markup, raising MarkupError on
    Static.update / render. The modal already escaped these via
    rich.markup.escape (config_modals.py:160); the fatal screen missed it.

    Fix: escape the error string before passing to Static.
    """
    # Real Pydantic ValidationError-style message (the [type=...] block is
    # what trips Rich markup parsing).
    err = (
        "1 validation error for PolilyConfig\n"
        "wallet.starting_balance\n"
        "  Input should be greater than or equal to 1 "
        "[type=greater_than_equal, input_value=0.5, input_type=float]\n"
        "    For further information visit "
        "https://errors.pydantic.dev/2.x/v/greater_than_equal"
    )
    screen = FatalConfigScreen(error_message=err)
    # Mounting the screen must NOT raise MarkupError (or anything else).
    async with _Harness(screen).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = "\n".join(
            str(w.render()) for w in screen.query("Static")
        )
        # Error content must reach the rendered output (literally, not
        # interpreted as markup).
        assert "starting_balance" in text
        # The literal `[type=` bracket survived (escaped, but visible)
        assert "type=greater_than_equal" in text


@pytest.mark.asyncio
async def test_fatal_screen_handles_real_pydantic_validation_error():
    """SF18 regression — construct a real Pydantic ValidationError, pass
    its str() to the fatal screen. Mounting must succeed.
    """
    from pydantic import ValidationError

    from polily.core.config import PolilyConfig

    # Real ValidationError from PolilyConfig
    err_str: str
    try:
        # starting_balance has Field(ge=1.0) — 0.5 will fail
        PolilyConfig(wallet={"starting_balance": 0.5})
    except ValidationError as ve:
        err_str = str(ve)
    else:
        pytest.fail("expected ValidationError to fire")

    # Real Pydantic message contains `[type=greater_than_equal, ...]`
    assert "[type=" in err_str

    screen = FatalConfigScreen(error_message=err_str)
    async with _Harness(screen).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Render does not raise; key fragment is visible
        text = "\n".join(
            str(w.render()) for w in screen.query("Static")
        )
        assert "starting_balance" in text
