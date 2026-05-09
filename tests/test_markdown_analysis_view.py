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
async def test_next_check_footer_renders_at_bottom_not_top():
    """v0.12.0 polish: the '⏰ 下次检查' status line goes AT THE BOTTOM,
    after the markdown body. User feedback: rendering it at the top
    pushes the actual analysis below the fold and makes the meta-info
    (when polily will re-check) feel more prominent than the analysis
    itself.
    """
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
        view = pilot.app.query_one(MarkdownAnalysisView)
        # Direct children of MarkdownAnalysisView in DOM order
        children = list(view.children)
        # Markdown body MUST come before the status line (Static)
        md_idx = next(
            (i for i, c in enumerate(children) if isinstance(c, Markdown)), -1,
        )
        status_idx = next(
            (i for i, c in enumerate(children) if isinstance(c, Static)), -1,
        )
        assert md_idx >= 0, "Markdown body widget should be a direct child"
        assert status_idx >= 0, "Status line should be a direct child"
        assert md_idx < status_idx, (
            f"Markdown body (idx {md_idx}) must come before "
            f"the next-check status line (idx {status_idx}); "
            f"current order is reversed (status first, body second)"
        )


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
