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


@pytest.mark.asyncio
async def test_section_starts_collapsed_except_movement(service):
    """Per design §5.2 — only movement is expanded by default."""
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        assert sections["movement"].expanded is True
        assert sections["scoring"].expanded is False
        assert sections["mispricing"].expanded is False
        assert sections["wallet"].expanded is False


@pytest.mark.asyncio
async def test_leaf_rows_show_english_last_segment_and_dim_full_key_path(service):
    """Per Q7 — main label is last_segment in English; second line is full key_path dim."""
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        movement_section = view.query_one("#body-movement")
        rows = list(movement_section.query("LeafRow"))
        # 5 scalar leaves (T5.6 only); weights tree comes in T5.8
        labels = [r.last_segment_label for r in rows[:5]]
        assert labels == [
            "magnitude_threshold",
            "quality_threshold",
            "daily_analysis_limit",
            "min_history_entries",
            "stale_threshold_seconds",
        ]
        # First row's full key_path is movement.magnitude_threshold
        assert rows[0].key_path == "movement.magnitude_threshold"


@pytest.mark.asyncio
async def test_leaf_row_shows_default_or_user_label(service):
    """Per design §5.2 — leaf row's source column shows '默认' or '你'."""
    from polily.core.config_store import upsert
    upsert(service.db, "movement.magnitude_threshold", 50)
    # Reload service config so loaded snapshot reflects edit
    service._config = service._load_default_config()

    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        rows = list(view.query("LeafRow"))
        rows_by_key = {r.key_path: r for r in rows}
        assert rows_by_key["movement.magnitude_threshold"].source_label == "你"
        assert rows_by_key["movement.quality_threshold"].source_label == "默认"
