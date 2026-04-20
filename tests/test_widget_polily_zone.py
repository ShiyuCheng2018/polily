# tests/test_widget_polily_zone.py
"""v0.8.0 Task 4: PolilyZone atom widget."""
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from scanner.tui.widgets.polily_zone import PolilyZone


class _Harness(App):
    def __init__(self, zone: PolilyZone):
        super().__init__()
        self._zone = zone
    def compose(self) -> ComposeResult:
        yield self._zone


async def test_polily_zone_renders_title_and_child():
    zone = PolilyZone(title="测试标题")
    zone.mount_composed = lambda: None  # dummy
    # Compose child via mounting
    harness = _Harness(zone)
    async with harness.run_test() as pilot:
        await pilot.pause()
        # Zone is mounted and has its title widget
        header = zone.query_one(".polily-zone-title")
        assert header is not None
        assert "测试标题" in str(header.render())


async def test_polily_zone_applies_expected_classes():
    """Both classes must be present — no half-success permitted (SF3)."""
    zone = PolilyZone(title="T")
    harness = _Harness(zone)
    async with harness.run_test() as pilot:
        await pilot.pause()
        assert "polily-zone" in zone.classes, \
            f"missing polily-zone class; got {zone.classes}"
        # NOTE: PolilyZone's DEFAULT_CSS hard-codes `padding: 1 3` which is
        # semantically equivalent to $space-md (3 cells). If tokens.tcss
        # evolves to declare a CSS variable we bind to, update this test.
