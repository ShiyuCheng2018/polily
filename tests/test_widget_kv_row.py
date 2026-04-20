# tests/test_widget_kv_row.py
"""v0.8.0 Task 7: KVRow atom."""
from textual.app import App, ComposeResult

from scanner.tui.widgets.kv_row import KVRow


class _Harness(App):
    def __init__(self, row: KVRow):
        super().__init__()
        self._row = row
    def compose(self) -> ComposeResult:
        yield self._row


async def test_kv_row_renders_label_and_value():
    row = KVRow(label="余额", value="$100.00")
    harness = _Harness(row)
    async with harness.run_test() as pilot:
        await pilot.pause()
        label = row.query_one(".kv-label")
        value = row.query_one(".kv-value")
        assert "余额" in str(label.render())
        assert "$100.00" in str(value.render())
