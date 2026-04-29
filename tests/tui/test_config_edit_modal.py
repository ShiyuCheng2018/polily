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
