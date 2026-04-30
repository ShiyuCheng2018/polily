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


@pytest.mark.asyncio
async def test_movement_weights_tree_renders_4_market_types(service):
    """Per design §5.2 — weights subtree under Movement, 4 market types."""
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        tree = view.query_one("#movement-weights-tree")
        market_types = [n.market_type for n in tree.query("MarketTypeNode")]
        assert market_types == ["crypto", "political", "economic_data", "default"]


@pytest.mark.asyncio
async def test_weights_show_sum_badge(service):
    """Each magnitude/quality family shows sum=X.XX."""
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        # Find crypto.magnitude family — its sum is 0.15+0.10+0.40+0.20+0.15 = 1.00
        node = view.query_one("#weights-crypto-magnitude")
        sum_text = "\n".join(
            str(s.render()) for s in node.query("Static")
        )
        assert "sum = 1.00" in sum_text or "sum=1.00" in sum_text


@pytest.mark.asyncio
async def test_section_header_shows_changed_count(service):
    """Per §5.2 — section header right side shows [已改 N/M]."""
    from polily.core.config_store import upsert
    upsert(service.db, "movement.magnitude_threshold", 50)

    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()
        movement_section_header = view.query_one("#header-movement", Static)
        text = str(movement_section_header.render())
        # 1 of 31 movement leaves changed (5 scalar + 26 weights)
        assert "已改 1 / 31" in text or "已改 1/31" in text


@pytest.mark.asyncio
async def test_config_view_subscribes_to_dedicated_heartbeat_topic(service):
    """SF10 — ConfigView listens to TOPIC_HEARTBEAT, not TOPIC_MONITOR_UPDATED.

    Locks the design intent: ConfigView's timer-based refresh must come from
    a dedicated heartbeat topic, not by hijacking a business-event topic.
    """
    from polily.core.events import TOPIC_HEARTBEAT, TOPIC_MONITOR_UPDATED
    view = ConfigView(service)
    async with _Harness(view).run_test() as pilot:
        await pilot.pause()

        # ConfigView should be subscribed to TOPIC_HEARTBEAT.
        # We verify behaviorally by publishing a heartbeat and checking
        # _refresh_state was called (it would update view.current_config
        # from db.config). Mock service's event_bus subscriber list if it
        # has _subscribers; otherwise verify by integration.
        bus = service.event_bus
        # Try direct attribute access first (most polily EventBus impls)
        if hasattr(bus, "_subscribers"):
            heartbeat_subs = bus._subscribers.get(TOPIC_HEARTBEAT, [])
            monitor_subs = bus._subscribers.get(TOPIC_MONITOR_UPDATED, [])
            # ConfigView's _on_heartbeat is bound to view; check by __self__
            assert any(
                getattr(cb, "__self__", None) is view for cb in heartbeat_subs
            ), "ConfigView didn't subscribe to TOPIC_HEARTBEAT"
            # AND must NOT have subscribed to monitor topic
            assert not any(
                getattr(cb, "__self__", None) is view for cb in monitor_subs
            ), "ConfigView wrongly subscribed to TOPIC_MONITOR_UPDATED"
        else:
            # Behavioral fallback: publish heartbeat, check view state changes
            from polily.core.config_store import upsert
            upsert(service.db, "movement.magnitude_threshold", 99)
            bus.publish(TOPIC_HEARTBEAT, {"source": "test"})
            await pilot.pause()
            assert view.current_config.get("movement.magnitude_threshold") == 99


@pytest.mark.asyncio
async def test_clicking_leaf_row_pushes_edit_modal(service):
    """LeafRow click → ConfigEditModal pushed onto screen stack."""
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Find the magnitude_threshold row and click it
        rows = list(view.query("LeafRow"))
        target = next(r for r in rows if r.key_path == "movement.magnitude_threshold")
        await pilot.click(target)
        await pilot.pause()
        # ConfigEditModal should now be on the screen stack
        from polily.tui.views.config_modals import ConfigEditModal
        assert any(isinstance(s, ConfigEditModal) for s in pilot.app.screen_stack)


@pytest.mark.asyncio
async def test_restart_invokes_scheduler_restart_subprocess(service, monkeypatch):
    """Whis B1 — restart action delegates to `polily scheduler restart`,
    NOT bare kill_daemon (which would crash-loop with KeepAlive=true).
    """
    invoked = []
    exit_called = {}

    def fake_run(cmd, *a, **kw):
        invoked.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os._exit", lambda code: exit_called.setdefault("code", code))
    monkeypatch.setattr(
        "polily.core.config_yaml.generate_yaml",
        lambda config, target: None,  # no-op
    )

    from polily.core.config_store import upsert
    upsert(service.db, "movement.magnitude_threshold", 50)
    service._config = service._load_default_config()

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view.action_restart_polily()
        await pilot.pause()
        # Skip the set_timer wait by calling the lambda directly if needed
        # — depends on how view implements the 2s exit delay.

    # Verify subprocess was called with `polily scheduler restart`
    assert any(
        isinstance(c, list) and "scheduler" in c and "restart" in c
        for c in invoked
    ), f"expected `scheduler restart` invocation, got: {invoked}"
    # Note: exit_called may or may not fire in test depending on timer behavior.
    # If timer doesn't fire in run_test scope, that's acceptable — verify only
    # the subprocess call.


# ---- B3: LeafRow keyboard accessibility ------------------------------------


@pytest.mark.asyncio
async def test_leaf_row_is_focusable(service):
    """B3 — LeafRow must be focusable so keyboard-only users can reach it.

    Without can_focus=True, Tab navigation skips the row and the only way to
    open the edit modal is mouse click.
    """
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        rows = list(view.query("LeafRow"))
        target = next(r for r in rows if r.key_path == "movement.magnitude_threshold")
        # The row class must declare can_focus
        assert target.can_focus is True
        # And focus() must succeed (raises if widget rejects focus)
        target.focus()
        await pilot.pause()
        assert target.has_focus


@pytest.mark.asyncio
async def test_pressing_enter_on_focused_leaf_opens_modal(service):
    """B3 — Enter on a focused LeafRow opens ConfigEditModal (keyboard parity)."""
    from polily.tui.views.config_modals import ConfigEditModal

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        rows = list(view.query("LeafRow"))
        target = next(r for r in rows if r.key_path == "movement.magnitude_threshold")
        target.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert any(isinstance(s, ConfigEditModal) for s in pilot.app.screen_stack)


@pytest.mark.asyncio
async def test_leaf_row_action_edit_directly_opens_modal(service):
    """B3 — action_edit() is the canonical keyboard handler; verify it routes
    through the same modal-push code path as on_click.
    """
    from polily.tui.views.config_modals import ConfigEditModal

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        rows = list(view.query("LeafRow"))
        target = next(r for r in rows if r.key_path == "movement.magnitude_threshold")
        target.action_edit()
        await pilot.pause()
        assert any(isinstance(s, ConfigEditModal) for s in pilot.app.screen_stack)
