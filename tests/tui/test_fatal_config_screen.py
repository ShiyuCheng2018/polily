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
