"""v0.8.0 Opt-B1: FieldRow atom.

Note on test harness: Textual's ``Input`` has reactive watchers that
eventually call ``self.app`` during ``__init__`` — constructing an Input
outside an active App context raises ``NoActiveAppError``. Each test
therefore builds its FieldRow (and the Input inside it) in the harness's
``compose`` hook, where the App context is active.
"""
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, Static

from scanner.tui.widgets.field_row import FieldRow


class _Harness(App):
    """Build the widget inside compose so Input's reactive setup runs in
    an active App context."""

    def __init__(self, build: Callable[[], FieldRow]) -> None:
        super().__init__()
        self._build = build
        self.row: FieldRow | None = None

    def compose(self) -> ComposeResult:
        self.row = self._build()
        yield self.row


async def test_renders_label_unit_input_helper():
    def build() -> FieldRow:
        inp = Input(value="10", id="amt", type="number")
        return FieldRow(
            label="金额", unit="$", input_widget=inp, helper="= 1000股",
        )

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        row = app.row
        label = row.query_one(".field-row-label", Label)
        unit = row.query_one(".field-row-unit", Static)
        helper = row.query_one(".field-row-helper", Static)
        rendered_label = str(getattr(label, "renderable", None) or label.render())
        assert "金额" in rendered_label
        rendered_unit = str(getattr(unit, "renderable", None) or unit.render())
        assert "$" in rendered_unit
        rendered_helper = str(getattr(helper, "renderable", None) or helper.render())
        assert "1000股" in rendered_helper
        # Input's id preserved — caller passed it in.
        assert row.query_one("#amt", Input) is not None


async def test_no_unit_omits_unit_span():
    def build() -> FieldRow:
        return FieldRow(label="名称", input_widget=Input(id="amt"))

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        # No .field-row-unit static rendered.
        units = list(app.row.query(".field-row-unit"))
        assert len(units) == 0


async def test_helper_has_id_when_provided():
    def build() -> FieldRow:
        return FieldRow(
            label="金额", unit="$", input_widget=Input(id="amt"),
            helper="", helper_id="preview",
        )

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.row.query_one("#preview", Static) is not None


async def test_set_helper_updates_helper_text():
    def build() -> FieldRow:
        return FieldRow(
            label="金额", unit="$", input_widget=Input(id="amt"),
            helper="initial",
        )

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.row.set_helper("updated")
        helper = app.row.query_one(".field-row-helper", Static)
        rendered = str(getattr(helper, "renderable", None) or helper.render())
        assert "updated" in rendered


async def test_input_receives_field_row_input_wrap_class():
    """Input passed in gets the atom's layout class added."""
    captured: dict = {}

    def build() -> FieldRow:
        inp = Input(id="amt")
        captured["inp"] = inp
        return FieldRow(label="名称", input_widget=inp)

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "field-row-input-wrap" in captured["inp"].classes


async def test_row_accepts_id_for_display_toggle():
    """Callers that toggle .display on the row need a stable id."""
    def build() -> FieldRow:
        return FieldRow(
            label="股数", input_widget=Input(id="amt"), helper="", id="my-row",
        )

    app = _Harness(build)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.row.id == "my-row"
        app.row.display = False
        assert app.row.display is False
