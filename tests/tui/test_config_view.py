"""ConfigView smoke tests (mount, sections present)."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget

from polily.tui.service import PolilyService
from polily.tui.views.config import ConfigView


class _Harness(App):
    """Minimal Textual app wrapping a single Widget for testing."""
    def __init__(self, widget: Widget):
        super().__init__()
        self._w = widget

    def compose(self) -> ComposeResult:
        yield self._w


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = PolilyService()
    yield svc
    svc.db.close()


@pytest.mark.asyncio
async def test_config_view_mounts_without_error(service):
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        assert view.is_mounted


@pytest.mark.asyncio
async def test_config_view_has_4_top_level_sections(service):
    """Per design §5.2 — Movement / Scoring / Mispricing / Wallet."""
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        section_titles = [w.section_id for w in view.query("ConfigSection")]
        assert section_titles == ["movement", "scoring", "mispricing", "wallet"]
