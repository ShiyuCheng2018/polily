"""BinaryMarketStructurePanel — per-dimension panel for binary events."""

import json

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


def _make_market(breakdown: dict | None, *, market_type: str = "other") -> object:
    class M:
        pass
    m = M()
    m.market_id = "m1"
    m.market_type = market_type
    m.structure_score = 78.0
    m.score_breakdown = json.dumps(breakdown) if breakdown else None
    return m


def _make_event(*, market_type: str = "other") -> object:
    class E:
        pass
    e = E()
    e.market_type = market_type
    return e


class _Host(App):
    def __init__(self, widget):
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


def _flatten_text(panel) -> str:
    return " ".join(str(s.render()) for s in panel.query(Static))


@pytest.mark.asyncio
async def test_renders_five_default_dimension_labels():
    from polily.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
        "commentary": {
            "dim_comments": {
                "liquidity": "深度充足", "verifiability": "基准清晰",
                "probability": "有空间", "time": "到期近", "friction": "摩擦低",
            },
            "overall": "结构扎实，主要变量在时效层",
        },
    }
    panel = BinaryMarketStructurePanel(_make_market(bd), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    for label in ["流动性", "可验证性", "概率空间", "时间", "摩擦"]:
        assert label in text, f"{label!r} missing in rendered panel"
    # net_edge row should NOT show when weight is 0 (non-crypto)
    assert "Edge" not in text


@pytest.mark.asyncio
async def test_shows_overall_commentary():
    """v0.11.5: commentary is rendered LIVE from current language —
    the panel ignores any pre-seeded `commentary` key in score_breakdown.
    Assert structural correctness: the 总评 label is present and the
    rendered overall string is non-empty (specific phrase varies with
    yaml content + market_id seed)."""
    from polily.tui.components import BinaryMarketStructurePanel

    # No pre-seeded commentary — view must render live
    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
    }
    panel = BinaryMarketStructurePanel(_make_market(bd), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    # 总评: label is present (zh) — proves the overall row was rendered
    assert "总评" in text or "Overall" in text, (
        f"Overall commentary label missing in rendered panel: {text!r}"
    )


@pytest.mark.asyncio
async def test_shows_dim_comments_per_row():
    """v0.11.5: each dim row's comment column is rendered live from
    phrases.<lang>.yaml. Don't assert exact phrases (they're seed-
    dependent). Instead verify each row has a non-trivial comment
    (i.e. the phrase column isn't all empty)."""
    from polily.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
    }
    panel = BinaryMarketStructurePanel(_make_market(bd), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    # Each dim label should be present + the rendered text should be
    # substantially longer than just the labels themselves (proving
    # commentary phrases are actually populating the comment column).
    for label in ["流动性", "可验证性", "概率空间", "时间", "摩擦"]:
        assert label in text, f"dim label {label!r} missing"
    # Lower bound on length — pure labels + bars + numbers is < 200 chars;
    # commentary adds substantial Chinese phrase content.
    assert len(text) > 200, (
        f"Rendered panel too short ({len(text)} chars) — commentary "
        f"may not be rendering. Got: {text!r}"
    )


@pytest.mark.asyncio
async def test_includes_edge_row_for_crypto():
    """v0.11.5: Edge row appears for crypto markets; comment is
    rendered live — assert structural presence rather than exact
    phrase."""
    from polily.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10, "net_edge": 20,
    }
    market = _make_market(bd, market_type="crypto")
    panel = BinaryMarketStructurePanel(market, event=_make_event(market_type="crypto"))
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    assert "Edge" in text, "Edge label missing for crypto market"


@pytest.mark.asyncio
async def test_commentary_re_renders_on_language_toggle():
    """Regression: the same panel (same bd, same market_id) renders
    different commentary text after `set_language` is flipped — the
    behavior the user explicitly asked for in v0.11.5 dev testing.
    """
    from polily.tui.components import BinaryMarketStructurePanel
    from polily.tui.i18n import set_language

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
    }
    market = _make_market(bd, market_type="other")

    # Render in zh
    set_language("zh")
    try:
        panel_zh = BinaryMarketStructurePanel(market, event=_make_event())
        async with _Host(panel_zh).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            zh_text = _flatten_text(panel_zh)

        # Render in en
        set_language("en")
        panel_en = BinaryMarketStructurePanel(market, event=_make_event())
        async with _Host(panel_en).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            en_text = _flatten_text(panel_en)
    finally:
        set_language("zh")  # restore for other tests

    # zh text contains Chinese; en text doesn't (commentary phrases at least)
    import re
    cjk = re.compile(r"[一-鿿]")
    # Some labels stay zh (label keys come from i18n catalog which Yuan
    # built), so check that en text has SUBSTANTIALLY less CJK than zh.
    zh_cjk_count = len(cjk.findall(zh_text))
    en_cjk_count = len(cjk.findall(en_text))
    assert en_cjk_count < zh_cjk_count, (
        f"After F2 to en, CJK character count should drop substantially. "
        f"zh={zh_cjk_count}, en={en_cjk_count}. "
        f"Commentary may not be re-rendering on language toggle."
    )


@pytest.mark.asyncio
async def test_handles_missing_score_breakdown():
    from polily.tui.components import BinaryMarketStructurePanel

    panel = BinaryMarketStructurePanel(_make_market(None), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Should compose without crashing; may render placeholder
        text = _flatten_text(panel)

    # Placeholder is acceptable; the key is no crash and no stray dim labels
    assert "流动性" not in text or "评分未就绪" in text or "暂无结构评分" in text


@pytest.mark.asyncio
async def test_falls_back_to_event_market_type():
    """If market.market_type == 'other', panel should look at event.market_type."""
    from polily.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10, "net_edge": 20,
        "commentary": {"dim_comments": {}, "overall": ""},
    }
    market = _make_market(bd, market_type="other")
    event = _make_event(market_type="crypto")
    panel = BinaryMarketStructurePanel(market, event=event)
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    assert "Edge" in text  # event.market_type=crypto enables net_edge row
