"""ConfigEditModal tests — modal mounts, displays markdown, save/cancel paths."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from polily.tui.service import PolilyService
from polily.tui.views.config_modals import ConfigEditModal


class _Harness(App):
    def __init__(self, modal: ConfigEditModal):
        super().__init__()
        self._modal = modal

    def on_mount(self) -> None:
        self.push_screen(self._modal)

    def compose(self) -> ComposeResult:
        yield from ()


@pytest.fixture
def service(tmp_path, monkeypatch):
    """v0.11.0 isolation: chdir + setenv POLILY_DATA_DIR.

    Without setenv, PolilyService() → default_db_path() → paths.db_path()
    resolves to user's real ~/Library/Application Support/polily/polily.db
    and tests pollute production data. Sibling test file
    test_event_detail_in_place.py had this exact bug; ev1 test event
    leaked into prod (verified 2026-05-03).
    """
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    svc = PolilyService()
    yield svc
    svc.db.close()
    paths.set_data_dir_override(None)


@pytest.mark.asyncio
async def test_modal_mounts_for_scalar_leaf(service):
    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=70,
        default_value=70,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        # PolilyCard renders title in its own Static; check the modal body
        # contains the leaf last_segment.
        keypath = modal.query_one("#modal-keypath", Static)
        assert "movement.magnitude_threshold" in str(keypath.render())


@pytest.mark.asyncio
async def test_modal_displays_markdown_description(service):
    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=70,
        default_value=70,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        markdown_widget = modal.query_one("#modal-description")
        # Markdown widget loads the `**默认 70。**` block from
        # config_docs/movement.md into its `source` attribute on compose;
        # render() returns Blank because content lives in mounted children.
        rendered = str(markdown_widget.source)
        assert "默认 70" in rendered or "magnitude_threshold" in rendered


@pytest.mark.asyncio
async def test_modal_rejects_construction_for_hidden_field(service):
    """HIDDEN_IN_TUI keys never reach the modal via UI, but defense-in-depth:
    if a caller tries to construct the modal for one, raise (T6.7)."""
    with pytest.raises(ValueError, match="not editable"):
        ConfigEditModal(
            service=service,
            key_path="archiving.db_file",
            current_value="./data/polily.db",
            default_value="./data/polily.db",
        )


@pytest.mark.asyncio
async def test_modal_rejects_construction_for_ephemeral_field(service):
    """T6.7 — api.user_agent (EPHEMERAL) cannot be edited."""
    with pytest.raises(ValueError, match="not editable"):
        ConfigEditModal(
            service=service,
            key_path="api.user_agent",
            current_value="polily/0.10.0",
            default_value="polily/0.10.0",
        )


@pytest.mark.asyncio
async def test_live_validation_shows_error_for_invalid_int(service):
    """Typing 'abc' for an int leaf shows red border + error text.

    SF14 — wait past the 100ms debounce window before asserting.
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        input_widget = modal.query_one("#modal-input", Input)
        input_widget.value = "abc"
        await asyncio.sleep(0.2)
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        rendered = str(error.render())
        assert "无法解析" in rendered or "invalid" in rendered.lower()


@pytest.mark.asyncio
async def test_live_validation_passes_for_valid_value(service):
    """SF14 — wait past the 100ms debounce window before asserting."""
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        input_widget = modal.query_one("#modal-input", Input)
        input_widget.value = "20"
        await asyncio.sleep(0.2)
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        assert str(error.render()).strip() == ""


@pytest.mark.asyncio
async def test_save_writes_to_db_and_dismisses_with_true(service):
    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=70,
        default_value=70,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal.query_one("#modal-input", Input).value = "55"
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()

    from polily.core.config_store import load_all
    flat = load_all(service.db)
    assert flat["movement.magnitude_threshold"] == 55


@pytest.mark.asyncio
async def test_save_rejects_value_failing_pydantic_validation(service):
    """starting_balance has Field(ge=1.0) — saving 0.5 must fail full validation."""
    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="wallet.starting_balance",
        current_value=100.0,
        default_value=100.0,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal.query_one("#modal-input", Input).value = "0.5"
        await pilot.pause()
        # Bypass pilot.click + event-dispatch race. The 100ms debounced
        # live-validation timer (SF14) can fire DURING pilot.click on slow
        # runners (Linux CI) — when it does, _run_live_validation calls
        # _show_error("") to clear the widget AFTER _do_save's error has
        # already been written, leaving the assertion looking at an empty
        # widget. The test is unit-testing _do_save's behavior; calling it
        # directly is a more honest white-box read.
        modal._cancel_validation_timer()
        modal._do_save()
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        # Prefer .renderable (what update() set) over .render() (which may
        # return a Blank placeholder if the widget hasn't repainted yet).
        rendered = str(getattr(error, "renderable", "") or error.render())
        # Pydantic ValidationError mentions the constraint
        assert ("ge" in rendered.lower()) or ("greater" in rendered.lower()) or ("1" in rendered), (
            f"Expected save-time Pydantic error to mention ge/greater/1; "
            f"got renderable={rendered!r}"
        )

    # db should NOT have the invalid value
    from polily.core.config_store import load_all
    flat = load_all(service.db)
    assert flat["wallet.starting_balance"] == 100.0


@pytest.mark.asyncio
async def test_reset_writes_default_and_updates_input(service):
    """Reset button writes Pydantic default to db AND updates the input field."""
    from textual.widgets import Input

    from polily.core.config_store import load_all, upsert

    upsert(service.db, "movement.magnitude_threshold", 50)

    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=50,
        default_value=70,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#reset-btn")
        await pilot.pause()
        # Input should reflect the default
        assert modal.query_one("#modal-input", Input).value == "70"

    flat = load_all(service.db)
    assert flat["movement.magnitude_threshold"] == 70


@pytest.mark.asyncio
async def test_cancel_button_dismisses_with_none(service):
    """Cancel discards user input — db unchanged even with invalid pending value."""
    from textual.widgets import Input

    from polily.core.config_store import load_all

    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=70,
        default_value=70,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal.query_one("#modal-input", Input).value = "999"  # would fail Pydantic validation if saved
        await pilot.click("#cancel")
        await pilot.pause()

    # db must be unchanged (cancel discards input)
    flat = load_all(service.db)
    assert flat["movement.magnitude_threshold"] == 70


@pytest.mark.asyncio
async def test_reset_re_enables_save_after_invalid_input(service):
    """SF5 — User typed invalid value → live validation disabled Save →
    user clicks Reset → Save must come back to life so they can save the
    default. Without explicit re-enable, the disabled flag could stick if
    `_show_error("")`'s contextlib.suppress swallowed any exception.
    """
    from textual.widgets import Button, Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.magnitude_threshold",
        current_value=70,
        default_value=70,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Type invalid value → live validation (debounced) should disable Save
        modal.query_one("#modal-input", Input).value = "abc"
        # SF14 — wait past the 100ms debounce window so validation fires.
        import asyncio
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled is True, (
            "Save should be disabled after invalid input"
        )

        # Click Reset
        await pilot.click("#reset-btn")
        await pilot.pause()

        # Save must be enabled again
        assert modal.query_one("#confirm", Button).disabled is False, (
            "Save must be re-enabled after Reset"
        )


@pytest.mark.asyncio
async def test_escape_key_dismisses_modal(service):
    """ESC binding dismisses the modal screen with None.

    Canonical polily pattern (per tests/test_wallet_view.py:186-191): instead of
    asserting `not modal.is_mounted` (unreliable for ModalScreen post-dismiss),
    use a host App that captures dismiss_result via callback.

    priority=True on the ESC Binding (config_modals.py:68) is required —
    otherwise the focused Input widget consumes escape before the screen-level
    binding fires.
    """
    from textual.app import App

    captured = {}

    class _CallbackHarness(App):
        def on_mount(self) -> None:
            self.push_screen(
                ConfigEditModal(
                    service=service,
                    key_path="movement.magnitude_threshold",
                    current_value=70,
                    default_value=70,
                ),
                lambda result: captured.setdefault("result", result),
            )

    async with _CallbackHarness().run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert captured.get("result") is None  # ESC → dismiss(None)


# ---- SF14: debounced live validation (CJK IME composition) ----------------


@pytest.mark.asyncio
async def test_live_validation_runs_after_debounce_window(service):
    """SF14 — typing fires Input.Changed but validation result lands only
    after the debounce window elapses. Without debounce, every keystroke
    runs `_resolve_field_annotation` + `_coerce_value` + Static.update, which
    lags during CJK IME composition (one event per pre-edit char).
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        input_widget = modal.query_one("#modal-input", Input)
        input_widget.value = "abc"
        # Short pause: timer hasn't fired yet (window is 100ms). Error
        # area should be empty (validation deferred).
        await pilot.pause()

        # Wait long enough for the debounce timer to fire.
        await asyncio.sleep(0.2)
        await pilot.pause()

        error = modal.query_one("#modal-error", Static)
        rendered = str(error.render())
        assert "无法解析" in rendered or "invalid" in rendered.lower(), (
            f"validation should have fired after debounce window, got: {rendered!r}"
        )


@pytest.mark.asyncio
async def test_rapid_input_changes_coalesce_to_single_validation(service, monkeypatch):
    """SF14 — N rapid Input.Changed events within the debounce window
    must collapse into ONE _run_live_validation call. Simulates CJK IME
    composition where typing "5" via pinyin fires 5+ Input.Changed events
    for pre-edit chars.
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        validation_calls = []
        original = modal._run_live_validation

        def counting_validation():
            validation_calls.append(None)
            return original()

        monkeypatch.setattr(modal, "_run_live_validation", counting_validation)

        # Fire 6 rapid input changes within the debounce window (100ms).
        input_widget = modal.query_one("#modal-input", Input)
        for ch in "abcdef":
            input_widget.value = ch
            # No pause between writes — they should all queue into one timer.

        # Wait past the window.
        await asyncio.sleep(0.2)
        await pilot.pause()

        # Coalesced: at most 1-2 calls (the final one). Definitely not 6.
        assert len(validation_calls) <= 2, (
            f"expected coalesced validation (≤2 calls), got {len(validation_calls)}"
        )


# ---- Round-2 (Goku #2): cancel pending validation timer on every dismiss ---


@pytest.mark.asyncio
async def test_escape_cancels_pending_validation_timer(service, monkeypatch):
    """Round-2 (Goku #2) — `_do_save` cancels the validation timer (good).
    `action_cancel` (ESC) does NOT. If user types invalid → ESC within
    100ms window, the timer fires after dismiss against a torn-down widget
    tree. `contextlib.suppress` in `_show_error` swallows the resulting
    `query_one` failure — no crash, but wasted call against a dead screen.

    Fix: `_cancel_validation_timer` helper called from every dismiss path
    (save / reset / cancel / ESC).
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )

    validation_calls = []
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        original = modal._run_live_validation

        def counting_validation():
            validation_calls.append(None)
            return original()

        monkeypatch.setattr(modal, "_run_live_validation", counting_validation)

        # Type invalid value → schedules a 100ms validation timer
        modal.query_one("#modal-input", Input).value = "abc"
        # Immediately dismiss via ESC, well within the 100ms window.
        modal.action_cancel()
        await pilot.pause()

        # Wait past the original 100ms window. With the cancel-on-dismiss
        # fix, the timer is stopped — validation should NOT fire.
        await asyncio.sleep(0.2)
        await pilot.pause()

    assert validation_calls == [], (
        f"validation timer fired after ESC dismiss — should be cancelled. "
        f"Calls: {len(validation_calls)}"
    )


@pytest.mark.asyncio
async def test_cancel_button_cancels_pending_validation_timer(
    service, monkeypatch,
):
    """Round-2 (Goku #2) — same as ESC but via the Cancel button
    (`on_confirm_cancel_bar_cancelled`).
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )

    validation_calls = []
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        original = modal._run_live_validation

        def counting_validation():
            validation_calls.append(None)
            return original()

        monkeypatch.setattr(modal, "_run_live_validation", counting_validation)

        modal.query_one("#modal-input", Input).value = "abc"
        # Bypass pilot.click — Linux CI is slow enough that pilot.click's
        # internal event-loop pumps elapse the 100ms wall-clock debounce
        # window BEFORE the click dispatches, defeating the race we want
        # to verify. Same fix shape as the save-rejection test (#90).
        # Direct call to the cancel-bar handler exercises the same code
        # path that the button click would trigger via Pressed → Cancelled.
        from polily.tui.widgets.confirm_cancel_bar import ConfirmCancelBar
        modal.on_confirm_cancel_bar_cancelled(ConfirmCancelBar.Cancelled())
        await pilot.pause()

        await asyncio.sleep(0.2)
        await pilot.pause()

    assert validation_calls == [], (
        f"validation timer fired after Cancel button — should be cancelled. "
        f"Calls: {len(validation_calls)}"
    )


@pytest.mark.asyncio
async def test_reset_cancels_pending_validation_timer(service, monkeypatch):
    """Round-2 (Goku #2) — Reset replaces the input with the default value,
    which itself fires `on_input_changed` and re-schedules the timer. But
    if a stale timer was already pending from prior typing, both timers
    would run — the stale one against the now-replaced input value.

    Fix: `_do_reset` cancels the pending timer up front, before the new
    value triggers a fresh timer.
    """
    import asyncio

    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )

    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Type invalid → schedules a timer
        modal.query_one("#modal-input", Input).value = "abc"
        # Click reset before the timer fires. After reset, the only
        # pending timer should be the one from setting input to "10"
        # (default), not the stale "abc" one. Either way, no crash and
        # the modal is in clean state.
        await pilot.click("#reset-btn")
        await pilot.pause()
        # Wait past the window for any pending timers to fire harmlessly
        await asyncio.sleep(0.2)
        await pilot.pause()

        # Modal is alive, error is cleared, input shows default.
        assert modal.query_one("#modal-input", Input).value == "10"


@pytest.mark.asyncio
async def test_cancel_validation_timer_is_idempotent(service):
    """Round-2 (Goku #2) — Helper must be safe to call when no timer is
    pending (e.g. dismiss before any keystroke).
    """
    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # No timer scheduled — helper should be a clean no-op.
        modal._cancel_validation_timer()
        modal._cancel_validation_timer()  # twice for idempotency
        assert modal._validation_timer is None


@pytest.mark.asyncio
async def test_action_cancel_clears_validation_timer_attribute(service):
    """Round-2 (Goku #2) — After action_cancel, _validation_timer must be
    None. Today (without the fix), action_cancel doesn't touch the timer
    field, so a pending timer reference lingers on the dismissed modal.

    This is the directly observable contract: helper called → field is None.
    """
    from textual.widgets import Input

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Type invalid → schedule a timer
        modal.query_one("#modal-input", Input).value = "abc"
        await pilot.pause()
        # Timer was scheduled by on_input_changed
        assert modal._validation_timer is not None, (
            "precondition: a validation timer should be pending after typing"
        )

        # ESC dismiss
        modal.action_cancel()

    # After cancel, the timer field must be None (cancelled + cleared)
    assert modal._validation_timer is None, (
        "action_cancel must cancel the pending validation timer"
    )


@pytest.mark.asyncio
async def test_cancel_bar_cancelled_clears_validation_timer_attribute(service):
    """Round-2 (Goku #2) — `on_confirm_cancel_bar_cancelled` (Cancel button)
    must also cancel the timer.
    """
    from textual.widgets import Input

    from polily.tui.widgets.confirm_cancel_bar import ConfirmCancelBar

    modal = ConfigEditModal(
        service=service,
        key_path="movement.daily_analysis_limit",
        current_value=10,
        default_value=10,
    )
    async with _Harness(modal).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal.query_one("#modal-input", Input).value = "abc"
        await pilot.pause()
        assert modal._validation_timer is not None

        # Simulate Cancel button event
        modal.on_confirm_cancel_bar_cancelled(
            ConfirmCancelBar.Cancelled(),  # type: ignore[call-arg]
        )

    assert modal._validation_timer is None, (
        "on_confirm_cancel_bar_cancelled must cancel the pending timer"
    )
