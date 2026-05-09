"""Render v0.12.0 markdown agent output in the TUI.

WYSIWYG via Textual's Markdown widget. Frontmatter is hidden (parsed for
the next-check status line only); body is rendered verbatim.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static

from polily.agents.frontmatter import split_frontmatter
from polily.analysis_store import AnalysisVersion
from polily.tui.i18n import t


class MarkdownAnalysisView(Vertical):
    """Displays AgentMarkdownOutput-style analyses (narrative_format='markdown').

    Layout (top → bottom):
      - Full markdown body via Textual's Markdown widget (WYSIWYG)
      - One-line footer showing next_check_at + reason (if present)

    The footer goes at the BOTTOM (not top) per v0.12.0 user feedback —
    the analysis is the primary content; "when will polily re-check"
    is meta-info. Reversing the order pushed the actual edge assessment
    below the fold on smaller terminals.

    Uses ``Vertical`` (NOT ``VerticalScroll``) — the parent ``EventDetailView``
    already wraps the analysis area in ``VerticalScroll``. Nesting our own
    scroll container would create double-scroll inside the event detail page
    (Textual reports it as competing scroll regions, hand-eye says "scroll
    inside scroll" which is broken UX). Height grows naturally with content;
    the outer scroll handles overflow.
    """

    DEFAULT_CSS = """
    MarkdownAnalysisView { height: auto; }
    MarkdownAnalysisView > .next-check-line {
        color: $text-muted;
        padding: 1 1 0 1;
    }
    """

    def __init__(self, av: AnalysisVersion, **kwargs) -> None:
        super().__init__(**kwargs)
        # narrative_output for markdown rows is `str` (or could be `dict` if
        # somehow a legacy row leaked here — defend by stringifying).
        raw = av.narrative_output if isinstance(av.narrative_output, str) else str(av.narrative_output)
        fm, body = split_frontmatter(raw)
        self._frontmatter = fm
        self._body = body or "_(empty body)_"

    def compose(self) -> ComposeResult:
        # Body first, footer last (see class docstring for rationale).
        yield Markdown(self._body)
        next_check_at = self._frontmatter.get("next_check_at", "")
        reason = self._frontmatter.get("next_check_reason", "")
        if next_check_at:
            label = t("analysis.next_check_label")
            yield Static(
                f"⏰ {label}: {next_check_at}  ·  {reason}",
                classes="next-check-line",
            )
