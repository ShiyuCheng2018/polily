"""v0.10.1 — event_detail must preserve scroll position on heartbeat refresh.

Pre-fix: refresh_data() called self.refresh(recompose=True) on
EventDetailView itself, which destroyed the outer VerticalScroll.
Each 5s heartbeat reset scroll_y to 0.

Fix: refresh_data orchestrates per-child update_data() calls. Each
child recomposes itself (Textual recompose is scoped to widget +
descendants, not ancestors), so the outer VerticalScroll is never
touched.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.tui.service import PolilyService
from polily.tui.views.event_detail import EventDetailView


class _Harness(App):
    """v0.10.1 review SF-A: use R5 ConfigView reference pattern
    (compose yields the view) instead of on_mount + self.mount(view).
    See tests/tui/test_config_view.py:13-20 for canonical example —
    the on_mount approach paints empty first then mounts, which can
    interact poorly with VerticalScroll's scroll_y initialization."""

    def __init__(self, view: EventDetailView):
        super().__init__()
        self._view = view

    def compose(self) -> ComposeResult:
        yield self._view


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = PolilyService()
    yield svc
    svc.db.close()


def _seed_event(service, event_id: str = "ev1") -> None:
    """Insert minimal event + market so EventDetailView has data to render."""
    now = datetime.now(UTC).isoformat()
    upsert_event(EventRow(
        event_id=event_id, title="Test event for scroll preservation",
        slug="test", market_count=1, updated_at=now,
    ), service.db)
    upsert_market(MarketRow(
        market_id="m1", event_id=event_id,
        question="Test market?", outcomes='["Yes","No"]',
        yes_price=0.55, no_price=0.45, volume=10000.0, updated_at=now,
    ), service.db)


@pytest.mark.asyncio
async def test_refresh_data_preserves_vertical_scroll_position(service):
    """5s heartbeat refresh must NOT reset the outer VerticalScroll's scroll_y.

    After refresh, we re-query VerticalScroll fresh: with the bug,
    self.refresh(recompose=True) detaches the original VerticalScroll
    (which retains its in-memory scroll_y attr) and mounts a NEW one
    with scroll_y=0. So we must compare against the live tree's
    current VerticalScroll, not the captured reference.
    """
    _seed_event(service)
    view = EventDetailView("ev1", service)
    async with _Harness(view).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scroll = view.query_one(VerticalScroll)
        scroll.scroll_to(y=10, animate=False)
        await pilot.pause()
        before = scroll.scroll_y
        # Sanity: scroll actually moved (otherwise the assertion below is meaningless)
        # If this fails after a layout change, EventDetailView no longer overflows
        # the 30-row terminal. Either grow `run_test(size=...)` height or seed more
        # content (e.g. multiple analyses) so scroll_to(y=10) doesn't clamp to 0.
        assert before > 0, "precondition: scroll_y should be non-zero after manual scroll"

        view.refresh_data()
        await pilot.pause()

        # Re-query: with the bug, the original `scroll` is detached but keeps
        # its in-memory scroll_y; the new VerticalScroll has scroll_y=0.
        scroll_after = view.query_one(VerticalScroll)
        after = scroll_after.scroll_y
        assert after == before, (
            f"scroll position lost on refresh — was {before}, now {after}. "
            f"refresh_data must orchestrate per-child update_data calls "
            f"instead of self.refresh(recompose=True)."
        )


@pytest.mark.asyncio
async def test_refresh_data_does_not_recompose_event_detail_view(service, monkeypatch):
    """White-box: ensure EventDetailView itself never recomposes.

    Children may recompose themselves (that's the in-place pattern), but
    EventDetailView.refresh(recompose=True) would defeat the whole fix.
    """
    _seed_event(service)
    view = EventDetailView("ev1", service)
    async with _Harness(view).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        recompose_calls = []
        original_refresh = view.refresh
        def spy(*args, **kwargs):
            if kwargs.get("recompose"):
                recompose_calls.append(kwargs)
            return original_refresh(*args, **kwargs)
        monkeypatch.setattr(view, "refresh", spy)

        # Pre: this seed has no analyses → AnalysisPanel mount transition is not
        # exercised. The one-time parent recompose at event_detail.py:298-301
        # (when analyses go empty→non-empty, or _analyzing flips True) is correct
        # and unavoidable; this test only pins that the steady-state heartbeat
        # path never recomposes EventDetailView.
        view.refresh_data()
        await pilot.pause()

        assert recompose_calls == [], (
            f"EventDetailView.refresh(recompose=True) must NEVER be called — "
            f"got {recompose_calls}. Children handle their own recomposition."
        )
