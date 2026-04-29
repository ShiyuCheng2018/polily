"""ConfigView smoke tests (mount, sections present)."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Static

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


@pytest.mark.asyncio
async def test_banner_shows_zero_when_no_pending_edits(service):
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        banner = view.query_one("#drift-banner", Static)
        rendered = str(banner.render())
        # Either shows "无未生效改动" or hidden state — fresh service has no edits
        assert "无未生效改动" in rendered or "0 项" in rendered


@pytest.mark.asyncio
async def test_banner_shows_count_when_user_edits_db(service):
    """User edits db → loaded_config != current_config → banner counts."""
    from polily.core.config_store import upsert
    upsert(service.db, "movement.magnitude_threshold", 50)
    upsert(service.db, "wallet.starting_balance", 200.0)

    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        banner = view.query_one("#drift-banner", Static)
        rendered = str(banner.render())
        # Per §5.2 — "[有 N 项改动未生效 · ⟲ 重启 polily 应用]"
        assert "2 项" in rendered
        assert "重启 polily" in rendered


def test_count_pending_changes_filters_ephemeral():
    """EPHEMERAL_FIELDS aren't counted in drift (they don't persist)."""
    from polily.tui.views.config import _count_pending_changes
    loaded = {"api.user_agent": "polily/0.10.0", "movement.magnitude_threshold": 70}
    current = {"api.user_agent": "polily/0.10.1", "movement.magnitude_threshold": 70}
    assert _count_pending_changes(loaded, current) == 0
