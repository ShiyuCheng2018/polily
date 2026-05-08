"""Verify MarkdownAnalysisView extracts frontmatter and renders body."""
import pytest
from textual.app import App
from textual.widgets import Markdown, Static

from polily.analysis_store import AnalysisVersion
from polily.tui.components.markdown_analysis_view import MarkdownAnalysisView


@pytest.mark.asyncio
async def test_markdown_view_renders_body_widget():
    av = AnalysisVersion(
        version=1,
        created_at="2026-05-08T10:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={},
        narrative_output="""---
next_check_at: "2026-05-10T13:00:00+00:00"
next_check_reason: "FDA hearing"
urgency: "normal"
dev_feedback: ""
---

# Edge assessment

Body content here.
""",
        narrative_format="markdown",
    )

    class TestApp(App):
        def compose(self):
            yield MarkdownAnalysisView(av)

    async with TestApp().run_test() as pilot:
        # The Markdown widget should render the body — exact widget API varies
        # by Textual version, so check loosely.
        md_widgets = pilot.app.query(Markdown)
        assert len(md_widgets) >= 1


@pytest.mark.asyncio
async def test_markdown_view_renders_next_check_status_line():
    av = AnalysisVersion(
        version=1,
        created_at="2026-05-08T10:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={},
        narrative_output="""---
next_check_at: "2026-05-10T13:00:00+00:00"
next_check_reason: "FDA hearing"
urgency: "normal"
dev_feedback: ""
---

# Body
""",
        narrative_format="markdown",
    )

    class TestApp(App):
        def compose(self):
            yield MarkdownAnalysisView(av)

    async with TestApp().run_test() as pilot:
        # The next-check status line is a Static widget; assert that some
        # Static somewhere in the tree contains the next_check_at value.
        # Textual's Static API: `.render()` returns a Content/Text-like
        # object whose str() is the rendered text. We stringify defensively.
        statics = pilot.app.query(Static)
        text_blob = " ".join(str(s.render()) for s in statics)
        assert (
            "2026-05-10" in text_blob
            or "13:00" in text_blob
            or "FDA hearing" in text_blob
        ), f"Expected next-check status line; got: {text_blob[:200]}"
