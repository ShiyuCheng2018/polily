"""default.md content sanity checks."""
from pathlib import Path

import polily


def test_default_md_has_five_sections():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(headings) == 5, f"Expected 5 H2 sections, got {len(headings)}: {headings}"


def test_default_md_event_type_dimensions_present():
    """v0.12.x selective recovery: event-type analytical dimensions per market_type."""
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    for mt in ("crypto", "political", "sports", "economic_data", "social"):
        assert mt in text, f"Missing event-type guidance for market_type={mt!r}"


def test_default_md_position_management_depth():
    """Position-management section must mention thesis_status semantics + cross-event awareness."""
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    for marker in ("thesis", "intact", "weakened", "broken"):
        assert marker in text.lower(), f"Position management depth missing {marker!r}"


def test_default_md_recommends_event_metadata_first():
    """v0.12.0 backlog #6: §1 must instruct the agent to read
    `events.event_metadata.context_description` BEFORE WebSearching for
    event background, when the description is fresh (≤24h). Saves one
    broad-strokes web call per analysis, surfaced as dev_feedback on
    2026-05-11 12:22 CST for event 108031.
    """
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    lower = text.lower()
    # Must mention event_metadata as a context source
    assert "event_metadata" in text, (
        "§1 must reference events.event_metadata as a primary context source"
    )
    # Must include a freshness boundary so agent knows when to trust it
    assert "24h" in text or "24 h" in text or "context_updated_at" in lower, (
        "§1 must specify when event_metadata is trustworthy (freshness window) "
        "so the agent has a deterministic decision rule"
    )
    # Must explicitly link reading event_metadata to saving a WebSearch call
    assert "websearch" in lower, (
        "§1 must connect event_metadata freshness to WebSearch decision"
    )


def test_default_md_pre_analysis_context_block():
    """§1 must instruct agent to gather context (prior analyses, movement, positions, wallet)
    before entering the Q1-Q5 framework — recovers v0.11.x's '查 DB 全貌' first-step guidance.
    """
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    for marker in (
        "Prior `analyses`",
        "movement_log",
        "positions",
        "wallet",
    ):
        assert marker in text, f"Pre-analysis context block missing reference to {marker!r}"


def test_default_md_contains_five_self_reflective_questions():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    for q in ("Q1.", "Q2.", "Q3.", "Q4.", "Q5."):
        assert q in text, f"Default strategy missing self-reflective {q}"


def test_default_md_mentions_has_position():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    assert "has_position" in text


def test_default_md_does_not_invite_meta_disclaimers():
    """v0.12.0 polish: §3 must not contain a slogan-style closer that
    agents echo back as a section-header parenthetical (e.g.
    '## 跨事件持仓背景（描述，不评判）'). The 'describe vs judge' rule
    must read as internal behavioral guidance, not a quotable maxim.
    """
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    # Catch-all: the previous slogan-y phrasing
    assert "Describing the data is the job; judging the user is overreach." not in text, (
        "§3 has the old slogan-style closer that agents echo as meta-disclaimers; "
        "rephrase as concrete behavioral guidance"
    )
    # Positive guard: must explicitly tell agent NOT to surface the rule
    lower = text.lower()
    assert "don't surface" in lower or "do not surface" in lower or "meta-noise" in lower, (
        "§3 must explicitly tell the agent NOT to surface the describe-vs-judge "
        "rule as parenthetical disclaimers in section headers"
    )


def test_default_md_market_id_must_have_friendly_label():
    """v0.12.0 polish: bare numeric market_ids in operations tables
    are illegible to users. Strategy must require a friendly label
    alongside the id.
    """
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    # Must reference both group_item_title (friendly source) AND require
    # both a label and the market_id together
    assert "group_item_title" in text or "friendly label" in text.lower(), (
        "default.md must reference 'group_item_title' or 'friendly label' "
        "so agents know to pair market_ids with human-readable names"
    )


def test_default_md_requires_source_citation_for_web_data():
    """v0.12.0 hotfix: every fact pulled via WebSearch must carry a source.

    The previous BTC $150k analysis cited "ETF Q1 2026 inflows $18.7B",
    "BlackRock IBIT AUM $54B", "30d funding rate -5%" with zero sources —
    user can't verify, can't tell if it's stale, can't tell if it's
    hallucinated. Default strategy must enforce explicit source attribution
    on web-collected data.
    """
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    lower = text.lower()
    # Must mention citing sources / source attribution
    assert "source" in lower or "cite" in lower or "citation" in lower, (
        "default.md must instruct the agent to cite sources for web-collected data"
    )
    # Must specifically reference WebSearch (the tool through which web data arrives)
    assert "websearch" in lower, (
        "default.md must reference WebSearch when discussing source citation "
        "(otherwise agent may not know the rule applies to its own tool calls)"
    )


def test_default_md_is_english_no_chinese():
    """Per Q1: agent prompts ship as English; user_lang directive switches output language."""
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    cjk = [c for c in text if "一" <= c <= "鿿"]
    assert cjk == [], f"default.md must be English; found CJK chars: {set(cjk)}"
