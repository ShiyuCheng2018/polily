"""ConfirmUnmonitorModal — asks for explicit confirmation before stopping
monitoring of an event. Used by both EventDetailView and MonitorListView.
"""

import pytest
from textual.app import App, ComposeResult


class _Host(App):
    def __init__(self, modal):
        super().__init__()
        self._modal = modal
        self.last_dismissed: bool | None = None

    def compose(self) -> ComposeResult:
        return []

    async def on_mount(self) -> None:
        self.push_screen(self._modal, self._capture)

    def _capture(self, value: bool | None) -> None:
        self.last_dismissed = value


@pytest.mark.asyncio
async def test_confirm_button_dismisses_true():
    from polily.tui.views.monitor_modals import ConfirmUnmonitorModal

    modal = ConfirmUnmonitorModal("US × Iran peace deal")
    app = _Host(modal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()

    assert app.last_dismissed is True


@pytest.mark.asyncio
async def test_keep_monitoring_button_dismisses_false():
    from polily.tui.views.monitor_modals import ConfirmUnmonitorModal

    modal = ConfirmUnmonitorModal("US × Iran peace deal")
    app = _Host(modal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()

    assert app.last_dismissed is False


@pytest.mark.asyncio
async def test_escape_dismisses_false():
    from polily.tui.views.monitor_modals import ConfirmUnmonitorModal

    modal = ConfirmUnmonitorModal("US × Iran peace deal")
    app = _Host(modal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.last_dismissed is False


@pytest.mark.asyncio
async def test_shows_event_title_in_prompt():
    """The modal should reference the event title so the user knows what
    they're about to stop monitoring."""
    from textual.widgets import Static

    from polily.tui.views.monitor_modals import ConfirmUnmonitorModal

    title = "US-Iran nuclear deal by April 30?"
    modal = ConfirmUnmonitorModal(title)
    app = _Host(modal)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        flat = " ".join(str(s.render()) for s in modal.query(Static))

    assert title in flat or title[:30] in flat
