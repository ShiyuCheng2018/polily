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
    monkeypatch.chdir(tmp_path)
    svc = PolilyService()
    yield svc
    svc.db.close()


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
    """Typing 'abc' for an int leaf shows red border + error text."""
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
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        rendered = str(error.render())
        assert "无法解析" in rendered or "invalid" in rendered.lower()


@pytest.mark.asyncio
async def test_live_validation_passes_for_valid_value(service):
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
        # Live validation passes (it's a float). Save-time validation fails.
        await pilot.click("#confirm")
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        rendered = str(error.render())
        # Pydantic ValidationError mentions the constraint
        assert ("ge" in rendered.lower()) or ("greater" in rendered.lower()) or ("1" in rendered)

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
