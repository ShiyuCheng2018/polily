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
