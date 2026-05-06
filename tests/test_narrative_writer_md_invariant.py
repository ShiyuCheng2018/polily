"""v0.11.7 invariant: narrative_writer.md must not contain `FROM markets`
or `JOIN markets` SQL templates.

AF-1 (v0.11.7) deleted three sqlite3 templates from the prompt that
let the agent re-query the markets table mid-analysis, causing
narrative-internal price inconsistency. The fix replaced them with a
frozen YAML prices block at prompt top.

Future regression risk: someone re-adds a `FROM markets` template to
the prompt thinking it's helpful for some new use case, undoing AF-1.
This test fails CI loudly if that happens.

Also asserts the new frozen-prices section IS present (so the prompt
file isn't accidentally truncated below the YAML block instructions)."""
from __future__ import annotations

import re
from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "polily" / "agents" / "prompts" / "narrative_writer.md"
)


# Whis-review S-3 (2026-05-07): use regex matching `sqlite3 ... FROM markets`
# pattern (executable SQL templates), NOT raw substring. A future contributor
# legitimately mentioning "we used to query FROM markets" in prose / a comment
# should NOT trip this invariant. Only actual sqlite3 SQL templates regress AF-1.
_FROM_MARKETS_SQL_RE = re.compile(
    r"sqlite3[^\n]*\bFROM\s+markets\b",
    re.IGNORECASE,
)
_JOIN_MARKETS_SQL_RE = re.compile(
    r"sqlite3[^\n]*\bJOIN\s+markets\b",
    re.IGNORECASE,
)


def test_prompt_md_no_from_markets_sql_template():
    """No executable `sqlite3 ... FROM markets` SQL template anywhere.

    Uses regex (not raw substring) so future legitimate prose mentions
    of "FROM markets" (e.g., comments explaining the AF-1 fix) don't
    trip the invariant.
    """
    text = PROMPT_PATH.read_text(encoding="utf-8")
    match = _FROM_MARKETS_SQL_RE.search(text)
    assert not match, (
        f"narrative_writer.md contains an executable `sqlite3 ... FROM markets` "
        f"SQL template at: {match.group()!r}. This re-introduces the AF-1 "
        f"price-consistency bug. Use the frozen prices YAML block at the top "
        f"of the prompt instead. See docs/internal/plans/completed/"
        f"2026-05-07-v0_11_7-implementation.md Task 8 for context."
    )


def test_prompt_md_no_join_markets_sql_template():
    """No executable `sqlite3 ... JOIN markets` SQL template — same reason."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    match = _JOIN_MARKETS_SQL_RE.search(text)
    assert not match, (
        f"narrative_writer.md contains a `sqlite3 ... JOIN markets` SQL "
        f"template at: {match.group()!r}. See test_prompt_md_no_from_markets_sql_template."
    )


def test_prompt_md_has_frozen_prices_section():
    """Positive invariant: the new "## 价格快照（已冻结）" block must
    be referenced in the prompt instructions so the agent knows where
    to read prices.

    The block is dynamically rendered into the prompt body at agent
    invocation time by `_render_frozen_prices_section`, so the md file
    has the *instructions* about it, not the literal block contents.
    Search for the instruction marker.
    """
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "价格快照" in text or "prices_snapshot_at" in text, (
        "narrative_writer.md does not reference the frozen prices block — "
        "the instructions to the agent must mention where prices come from."
    )


def test_prompt_md_has_universal_5_questions():
    """Positive invariant: the AF-5b universal 5-question frame must
    be present (or the prompt has been silently re-vagued)."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "分析框架（所有 market_type 通用）" in text, (
        "narrative_writer.md missing the universal analysis frame "
        "section header. AF-5b removed two vague non-crypto sentences "
        "and replaced them with this universal 5-question block. If "
        "you removed it, please replace with an equivalent or better "
        "interrogative frame — don't go back to the vague phrasing."
    )


def test_prompt_md_documents_implied_fair_value():
    """Positive invariant: the AF-3 prompt note about
    score_breakdown.implied_fair_value is present."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "implied_fair_value" in text, (
        "narrative_writer.md must mention `implied_fair_value` so the "
        "agent knows about the negRisk completeness anchor when reading "
        "score_breakdown."
    )
