"""Frontmatter splitter — extracts YAML frontmatter from agent markdown output."""
from polily.agents.frontmatter import split_frontmatter


def test_well_formed_frontmatter():
    raw = """---
next_check_at: "2026-05-10T13:00:00+00:00"
next_check_reason: "FDA hearing"
urgency: "normal"
dev_feedback: "looks fine"
---

# Edge assessment

Body content here.
"""
    fm, body = split_frontmatter(raw)
    assert fm["next_check_at"] == "2026-05-10T13:00:00+00:00"
    assert fm["next_check_reason"] == "FDA hearing"
    assert fm["urgency"] == "normal"
    assert fm["dev_feedback"] == "looks fine"
    assert body.strip().startswith("# Edge assessment")


def test_no_frontmatter_returns_empty_dict_and_full_body():
    raw = "# Just a body\n\nNo frontmatter here.\n"
    fm, body = split_frontmatter(raw)
    assert fm == {}
    assert body == raw


def test_malformed_yaml_returns_empty_dict_with_full_body():
    """Defensive: garbage in frontmatter yields {} (semantic_errors will catch missing fields later)."""
    raw = """---
this is not: valid: yaml: at all
---

# Body
"""
    fm, body = split_frontmatter(raw)
    assert fm == {}
    # Body in this defensive case is the entire input (caller treats whole output as body)
    assert "# Body" in body


def test_frontmatter_only_no_body():
    raw = """---
next_check_at: "2026-05-10T13:00:00+00:00"
---
"""
    fm, body = split_frontmatter(raw)
    assert fm["next_check_at"] == "2026-05-10T13:00:00+00:00"
    assert body.strip() == ""


def test_frontmatter_with_unicode_and_special_chars():
    raw = """---
next_check_reason: "FDA 听证会前 1 小时"
dev_feedback: "数据时效性 section 有效，agent 不再误报 race"
---

# 中文 body
"""
    fm, body = split_frontmatter(raw)
    assert fm["next_check_reason"] == "FDA 听证会前 1 小时"
    assert "中文 body" in body


# --- Preamble tolerance (v0.12.0 hotfix) ---
#
# Real-world agent outputs occasionally include a status preamble before
# the YAML block (e.g., "数据已收集完毕，生成完整分析." / "Here's the analysis:").
# protocol.md forbids this, but defensive parsing prevents one stray line
# from silently dropping the entire frontmatter. The dropped preamble is
# treated as noise (not surfaced in body) so the TUI markdown view stays
# clean.


def test_tolerates_single_line_chinese_preamble():
    raw = """数据已收集完毕，生成完整分析。

---
next_check_at: "2026-05-16T16:00:00+00:00"
next_check_reason: "BTC 价格趋势"
urgency: "no_rush"
dev_feedback: "v1 was meta-analysis; v2 is real"
---

# Edge assessment

Body here.
"""
    fm, body = split_frontmatter(raw)
    assert fm["next_check_at"] == "2026-05-16T16:00:00+00:00"
    assert fm["urgency"] == "no_rush"
    # Preamble is dropped — body starts with the markdown body, not the preamble
    assert "数据已收集完毕" not in body
    assert body.lstrip().startswith("# Edge assessment")


def test_tolerates_english_preamble():
    raw = """Here's the analysis:

---
urgency: "normal"
next_check_at: "2026-05-10T13:00:00+00:00"
---

# Body
"""
    fm, body = split_frontmatter(raw)
    assert fm["urgency"] == "normal"
    assert "Here's the analysis" not in body


def test_tolerates_leading_blank_lines():
    raw = """

---
urgency: "normal"
---

# Body
"""
    fm, body = split_frontmatter(raw)
    assert fm["urgency"] == "normal"
    assert body.lstrip().startswith("# Body")


def test_no_yaml_content_between_fences_returns_empty():
    """If the content between two `---` fences is not a YAML mapping
    (e.g., the agent emitted prose between two horizontal rules with no
    frontmatter at all), return ({}, raw) — never silently fabricate fields."""
    raw = """Some intro text.

---
This is just prose, not YAML key: value.
Another line.
---

# Body
"""
    fm, body = split_frontmatter(raw)
    # YAML lib will parse this as a string scalar, not a mapping → reject
    assert fm == {}
    assert body == raw


def test_preamble_with_horizontal_rule_after_yaml_block_unaffected():
    """Body horizontal rules (after the closing `---`) must not confuse the parser."""
    raw = """preamble

---
urgency: "normal"
---

# Body

Section 1.

---

Section 2 (separated by horizontal rule).
"""
    fm, body = split_frontmatter(raw)
    assert fm["urgency"] == "normal"
    assert "Section 1" in body
    assert "Section 2" in body
