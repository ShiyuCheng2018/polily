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


def test_count_pending_changes_skips_keys_only_in_current():
    """SF11 — keys present in current (db) but missing from loaded snapshot
    are NOT counted as drift. Avoids ghost drift in the hot-upgrade case
    where db schema is newer than the TUI's loaded PolilyConfig, or when
    the db has leftover keys from a partial migration / manual insert.
    """
    from polily.tui.views.config import _count_pending_changes
    loaded = {"movement.magnitude_threshold": 70}
    # db has an extra key (e.g., new field added by daemon's newer schema,
    # or stale leftover) that loaded snapshot doesn't know about
    current = {"movement.magnitude_threshold": 70, "movement.future_field": 999}
    assert _count_pending_changes(loaded, current) == 0


def test_count_pending_changes_counts_real_diffs_only():
    """SF11 regression — actual user edits (key in BOTH dicts, values differ)
    must still be counted; the new 'k in current' guard mustn't mask real drift.
    """
    from polily.tui.views.config import _count_pending_changes
    loaded = {"movement.magnitude_threshold": 70, "wallet.starting_balance": 100.0}
    current = {"movement.magnitude_threshold": 50, "wallet.starting_balance": 100.0}
    assert _count_pending_changes(loaded, current) == 1


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
        # SF17 — subprocess now runs on a worker thread; wait for it.
        await view.workers.wait_for_complete()
        await pilot.pause()

    # Verify subprocess was called with `polily scheduler restart`
    assert any(
        isinstance(c, list) and "scheduler" in c and "restart" in c
        for c in invoked
    ), f"expected `scheduler restart` invocation, got: {invoked}"
    # Note: exit_called may or may not fire in test depending on timer behavior.
    # If timer doesn't fire in run_test scope, that's acceptable — verify only
    # the subprocess call.


# ---- SF4: restart subprocess fail-loud -------------------------------------


@pytest.mark.asyncio
async def test_restart_does_not_exit_when_subprocess_returns_nonzero(
    service, monkeypatch,
):
    """SF4 — if `polily scheduler restart` returns non-zero rc, surface error
    via notify and DO NOT schedule os._exit. Otherwise the TUI silently exits
    while the daemon stays dead → user reopens 30s later and discovers nothing
    is running.
    """
    timer_calls = []
    notify_calls = []

    def fake_run(cmd, *a, **kw):
        return type("R", (), {
            "returncode": 1,
            "stderr": "launchctl: bootstrap denied",
            "stdout": "",
        })()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "polily.core.config_yaml.generate_yaml",
        lambda config, target: None,
    )

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Patch view.set_timer + notify after mount so we capture the calls
        monkeypatch.setattr(
            view, "set_timer",
            lambda delay, fn: timer_calls.append((delay, fn)),
        )
        monkeypatch.setattr(
            view, "notify",
            lambda msg, **kw: notify_calls.append((msg, kw)),
        )
        view.action_restart_polily()
        # SF17 — wait for worker to finish then drain UI events.
        await view.workers.wait_for_complete()
        await pilot.pause()

    # No exit timer scheduled
    assert timer_calls == [], (
        f"set_timer should NOT have been called on subprocess failure, "
        f"got: {timer_calls}"
    )
    # Error notify fired
    assert any(
        kw.get("severity") == "error" and "失败" in msg
        for msg, kw in notify_calls
    ), f"expected error notify on rc=1, got: {notify_calls}"


@pytest.mark.asyncio
async def test_restart_does_not_exit_when_subprocess_raises(service, monkeypatch):
    """SF4 — if subprocess.run raises (TimeoutExpired / FileNotFoundError /
    PermissionError), surface error via notify and DO NOT exit."""
    import subprocess

    timer_calls = []
    notify_calls = []

    def fake_run(cmd, *a, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "polily.core.config_yaml.generate_yaml",
        lambda config, target: None,
    )

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(
            view, "set_timer",
            lambda delay, fn: timer_calls.append((delay, fn)),
        )
        monkeypatch.setattr(
            view, "notify",
            lambda msg, **kw: notify_calls.append((msg, kw)),
        )
        view.action_restart_polily()
        # SF17 — wait for worker to finish then drain UI events.
        await view.workers.wait_for_complete()
        await pilot.pause()

    assert timer_calls == [], (
        f"set_timer should NOT fire when subprocess raises, got: {timer_calls}"
    )
    assert any(
        kw.get("severity") == "error" and "失败" in msg
        for msg, kw in notify_calls
    ), f"expected error notify on subprocess raise, got: {notify_calls}"


@pytest.mark.asyncio
async def test_restart_schedules_exit_only_on_subprocess_success(
    service, monkeypatch,
):
    """SF4 — happy path: rc=0 → set_timer fires for the os._exit call."""
    timer_calls = []

    def fake_run(cmd, *a, **kw):
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "polily.core.config_yaml.generate_yaml",
        lambda config, target: None,
    )

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(
            view, "set_timer",
            lambda delay, fn: timer_calls.append((delay, fn)),
        )
        view.action_restart_polily()
        # SF17 — wait for worker to finish then drain UI events.
        await view.workers.wait_for_complete()
        await pilot.pause()

    assert len(timer_calls) == 1, (
        f"expected 1 set_timer call on success, got: {timer_calls}"
    )
    # Delay should be the existing 2.0s grace period
    assert timer_calls[0][0] == 2.0


# ---- SF17: restart subprocess runs on worker thread (UI stays responsive) --


@pytest.mark.asyncio
async def test_restart_action_returns_immediately_on_slow_subprocess(
    service, monkeypatch,
):
    """SF17 — action_restart_polily must NOT block the event loop. With a
    slow subprocess (e.g. hung daemon restart), a synchronous subprocess.run
    would freeze the UI for up to 10s. The fix moves it to a worker thread
    so action_restart_polily returns immediately and the event loop keeps
    pumping.

    We measure: (a) the action call itself returns near-instantly, (b) the
    subprocess actually runs (proves the worker dispatched and didn't get
    stuck on the main thread).
    """
    import asyncio
    import threading
    import time

    started = threading.Event()
    release = threading.Event()
    captured_thread: dict[str, int] = {}

    def slow_run(cmd, *a, **kw):
        captured_thread["tid"] = threading.get_ident()
        started.set()
        # Block until the test releases us. If this ran on the event loop
        # thread, the asyncio.sleep below would never get to run.
        release.wait(timeout=5)
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("subprocess.run", slow_run)
    monkeypatch.setattr(
        "polily.core.config_yaml.generate_yaml",
        lambda config, target: None,
    )
    monkeypatch.setattr("os._exit", lambda code: None)

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        main_tid = threading.get_ident()
        # Fire the action: with a worker, this returns immediately;
        # without one, it would block on slow_run for 5s.
        t0 = time.perf_counter()
        view.action_restart_polily()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, (
            f"action_restart_polily blocked for {elapsed:.2f}s — "
            f"subprocess is not running on a worker thread"
        )

        # Yield to event loop a few times so the worker thread can spin up.
        # asyncio.sleep(0) repeatedly gives Textual's worker dispatch a
        # chance to start the thread.
        for _ in range(20):
            await asyncio.sleep(0.02)
            if started.is_set():
                break

        assert started.is_set(), (
            "subprocess never started — worker dispatch broken"
        )
        # Subprocess must have run on a different thread than the event loop.
        assert captured_thread["tid"] != main_tid, (
            "subprocess ran on the main/event-loop thread — worker not threaded"
        )

        # Release the subprocess so the worker can finish and the test
        # can clean up cleanly.
        release.set()
        await view.workers.wait_for_complete()
        await pilot.pause()


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


# ---- B4: ConfigView state preservation across modal close -----------------


@pytest.mark.asyncio
async def test_post_modal_save_preserves_section_expanded_state(service):
    """B4 — User expands `wallet`, edits a wallet leaf, save dismisses modal:
    the wallet section must still be expanded (not snap back to default).
    """
    from polily.core.config_store import upsert

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        wallet_section = sections["wallet"]
        # Simulate user expanding the wallet section.
        wallet_section.expanded = True
        wallet_section.remove_class("collapsed")
        await pilot.pause()
        assert wallet_section.expanded is True

        # Simulate a save: db gets updated, then the modal-close callback
        # re-reads state. After the in-place refresh, wallet must STILL be
        # expanded (movement is the only one expanded by default).
        upsert(service.db, "wallet.starting_balance", 200.0)
        leaf = next(
            r for r in view.query("LeafRow")
            if r.key_path == "wallet.starting_balance"
        )
        leaf._on_modal_closed(True)
        await pilot.pause()

        # Re-query (in-place update should preserve identity, but be defensive).
        sections_after = {s.section_id: s for s in view.query("ConfigSection")}
        assert sections_after["wallet"].expanded is True, (
            "wallet section was force-collapsed after modal close — "
            "recompose=True wiped expand state"
        )


@pytest.mark.asyncio
async def test_post_modal_save_updates_leaf_value_in_place(service):
    """B4 — After save, the LeafRow's displayed value must reflect the new
    db value (not the stale current_value the row was constructed with).
    """
    from polily.core.config_store import upsert

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        leaf_before = next(
            r for r in view.query("LeafRow")
            if r.key_path == "movement.magnitude_threshold"
        )
        original = leaf_before.current_value

        # Simulate user editing via modal: db updated, modal dismissed.
        upsert(service.db, "movement.magnitude_threshold", 99)
        leaf_before._on_modal_closed(True)
        await pilot.pause()

        # The leaf at this key_path must reflect the new value. Use query
        # rather than the original ref since in-place update may or may
        # not preserve widget identity.
        leaf_after = next(
            r for r in view.query("LeafRow")
            if r.key_path == "movement.magnitude_threshold"
        )
        assert leaf_after.current_value == 99
        assert leaf_after.current_value != original


@pytest.mark.asyncio
async def test_post_modal_save_updates_drift_banner(service):
    """B4 — Drift banner reflects new pending count after a save."""
    from polily.core.config_store import upsert

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        banner = view.query_one("#drift-banner", Static)
        # Fresh view: 0 pending.
        assert "无未生效改动" in str(banner.render())

        upsert(service.db, "movement.magnitude_threshold", 50)
        leaf = next(
            r for r in view.query("LeafRow")
            if r.key_path == "movement.magnitude_threshold"
        )
        leaf._on_modal_closed(True)
        await pilot.pause()

        banner_after = view.query_one("#drift-banner", Static)
        assert "1 项" in str(banner_after.render())


@pytest.mark.asyncio
async def test_post_modal_save_updates_section_count_badge(service):
    """B4 — Section header [已改 N/M] badge updates after a save."""
    from polily.core.config_store import upsert

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        header_before = view.query_one("#header-movement", Static)
        assert "已改 0" in str(header_before.render())

        upsert(service.db, "movement.magnitude_threshold", 50)
        leaf = next(
            r for r in view.query("LeafRow")
            if r.key_path == "movement.magnitude_threshold"
        )
        leaf._on_modal_closed(True)
        await pilot.pause()

        header_after = view.query_one("#header-movement", Static)
        assert "已改 1" in str(header_after.render())


@pytest.mark.asyncio
async def test_action_refresh_preserves_expanded_state(service):
    """B4 — `r` keystroke (action_refresh) must NOT collapse expanded sections."""
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        sections["scoring"].expanded = True
        sections["scoring"].remove_class("collapsed")
        await pilot.pause()

        view.action_refresh()
        await pilot.pause()

        sections_after = {s.section_id: s for s in view.query("ConfigSection")}
        assert sections_after["scoring"].expanded is True


# ---- SF16: empty PolilyCard removed (wrap VerticalScroll inside) ----------


@pytest.mark.asyncio
async def test_config_card_wraps_section_scroll(service):
    """SF16 — Previously the ConfigView yielded a sibling PolilyCard with
    no children plus a separate VerticalScroll. Result: a stray bordered
    "配置" card with empty body taking vertical space between the drift
    banner and the section list.

    Fix: VerticalScroll lives INSIDE the PolilyCard (option b — title
    labels the scroll region, matches wallet.py:135-137 pattern). The
    config-card must contain config-scroll as a descendant.
    """
    from textual.containers import VerticalScroll

    from polily.tui.widgets.polily_card import PolilyCard

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        card = view.query_one("#config-card", PolilyCard)
        # The VerticalScroll must be a descendant of the card, not a sibling
        scrolls_inside_card = list(card.query(VerticalScroll))
        assert len(scrolls_inside_card) == 1, (
            "config-scroll must be nested inside #config-card "
            "(SF16 — no more empty card)"
        )
        assert scrolls_inside_card[0].id == "config-scroll"


@pytest.mark.asyncio
async def test_config_card_is_not_empty(service):
    """SF16 — PolilyCard must not be a sibling-with-no-children (visual
    smell test). It should contain the config-scroll which contains all
    sections, so its descendants include at least the 4 ConfigSections.
    """
    from polily.tui.widgets.polily_card import PolilyCard

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        card = view.query_one("#config-card", PolilyCard)
        sections_inside = list(card.query("ConfigSection"))
        assert len(sections_inside) == 4, (
            "config-card must contain the 4 sections "
            "(SF16 — empty card was removed/refilled)"
        )


# ---- SF15: ConfigSection keyboard accessibility ----------------------------


@pytest.mark.asyncio
async def test_config_section_is_focusable(service):
    """SF15 — ConfigSection has BINDINGS = [Binding('enter', 'toggle')]
    but the binding never fires for keyboard nav unless the widget itself
    is focusable. Without can_focus=True, Tab navigation skips the section
    header and the only way to toggle is mouse click.
    """
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = list(view.query("ConfigSection"))
        assert all(s.can_focus is True for s in sections), (
            "ConfigSection must be focusable for keyboard Enter/Space to work"
        )
        # And focus() must succeed
        sections[0].focus()
        await pilot.pause()
        assert sections[0].has_focus


@pytest.mark.asyncio
async def test_pressing_enter_on_focused_section_toggles_expanded(service):
    """SF15 — Enter on a focused (collapsed) ConfigSection expands it,
    and Enter again collapses it. Mirrors the action_toggle binding.
    """
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        scoring = sections["scoring"]
        # scoring starts collapsed
        assert scoring.expanded is False

        scoring.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert scoring.expanded is True, (
            "Enter on focused ConfigSection should expand it"
        )

        await pilot.press("enter")
        await pilot.pause()
        assert scoring.expanded is False


@pytest.mark.asyncio
async def test_pressing_space_on_focused_section_toggles_expanded(service):
    """SF15 — Space is a common alternate key for toggle in TUI / web a11y
    conventions. Both Enter and Space should fire action_toggle.
    """
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        mispricing = sections["mispricing"]
        assert mispricing.expanded is False

        mispricing.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert mispricing.expanded is True


# ---- SF12: heartbeat skips refresh while modal is on top -------------------


@pytest.mark.asyncio
async def test_heartbeat_skips_refresh_while_modal_is_open(service, monkeypatch):
    """SF12 — when ConfigEditModal is pushed on top of the main screen,
    heartbeat refresh should short-circuit. No point updating a hidden
    view, and avoids any subtle stale-snapshot race between heartbeat-
    driven refresh and the modal's save → dismiss-callback flow.
    """
    from polily.tui.views.config_modals import ConfigEditModal

    refresh_calls = []

    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Patch the in-place refresh to count invocations
        monkeypatch.setattr(
            view, "_refresh_and_redraw",
            lambda: refresh_calls.append("called"),
        )

        # Baseline: heartbeat without modal does refresh
        view._on_heartbeat({})
        await pilot.pause()
        baseline = len(refresh_calls)
        assert baseline >= 1, "heartbeat should refresh when no modal is open"

        # Push a modal on top
        view.app.push_screen(
            ConfigEditModal(
                service=service,
                key_path="movement.magnitude_threshold",
                current_value=70,
                default_value=70,
            ),
        )
        await pilot.pause()

        # Heartbeat fires while modal is on top — should NOT refresh
        view._on_heartbeat({})
        await pilot.pause()
        assert len(refresh_calls) == baseline, (
            f"heartbeat must skip refresh while modal is on top, "
            f"got {len(refresh_calls) - baseline} extra calls"
        )


# ---- Round-2: _count_section_changes resilience to stale db keys -----------


@pytest.mark.asyncio
async def test_count_section_changes_skips_keys_missing_from_defaults(service):
    """Round-2 (Whis #2) — Twin of SF11 fix on the section-level counter.

    `_count_pending_changes` was hardened by SF11 to skip keys not in
    `loaded_config`. The same crash shape (`view.default_config[k]` raising
    KeyError) still exists in `_count_section_changes`. If the db happens
    to have a key not in PolilyConfig defaults (future schema rename leaves
    a stale db.config row, partial migration leftover), the section header
    re-render crashes the entire view mount.

    Fix: skip stale keys (treat as not-an-edit) — matches SF11's intent.
    """
    view = ConfigView(service)
    async with _Harness(view).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sections = {s.section_id: s for s in view.query("ConfigSection")}
        movement_section = sections["movement"]

        # Simulate a stale db row that defaults doesn't know about.
        # Pre-fix: _count_section_changes would do view.default_config[k]
        # → KeyError. Post-fix: skips it cleanly.
        view.current_config["movement.future_field_not_in_defaults"] = 999

        # Should not crash — and the count of edited leaves should remain 0
        # (the stale key is skipped, not counted as an edit).
        changed, total = movement_section._count_section_changes()
        assert changed == 0, (
            f"stale key (only in current, not defaults) must not be counted "
            f"as drift, got changed={changed}"
        )
        # And update_count_badge (which calls _count_section_changes) must
        # also not crash.
        movement_section.update_count_badge()
