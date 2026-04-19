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
    from scanner.tui.components import BinaryMarketStructurePanel

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
    from scanner.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
        "commentary": {"dim_comments": {}, "overall": "结构扎实，主要变量在时效层"},
    }
    panel = BinaryMarketStructurePanel(_make_market(bd), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    assert "结构扎实，主要变量在时效层" in text


@pytest.mark.asyncio
async def test_shows_dim_comments_per_row():
    from scanner.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10,
        "commentary": {
            "dim_comments": {
                "liquidity": "流动性描述X", "verifiability": "可验证性描述Y",
                "probability": "概率空间Z", "time": "时间窗W", "friction": "摩擦V",
            },
            "overall": "",
        },
    }
    panel = BinaryMarketStructurePanel(_make_market(bd), event=_make_event())
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    for phrase in ["流动性描述X", "可验证性描述Y", "概率空间Z", "时间窗W", "摩擦V"]:
        assert phrase in text, f"dim comment {phrase!r} missing"


@pytest.mark.asyncio
async def test_includes_edge_row_for_crypto():
    from scanner.tui.components import BinaryMarketStructurePanel

    bd = {
        "liquidity": 18, "verifiability": 8, "probability": 15,
        "time": 12, "friction": 10, "net_edge": 20,
        "commentary": {
            "dim_comments": {"net_edge": "Edge评分高"},
            "overall": "",
        },
    }
    market = _make_market(bd, market_type="crypto")
    panel = BinaryMarketStructurePanel(market, event=_make_event(market_type="crypto"))
    async with _Host(panel).run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _flatten_text(panel)

    assert "Edge" in text
    assert "Edge评分高" in text


@pytest.mark.asyncio
async def test_handles_missing_score_breakdown():
    from scanner.tui.components import BinaryMarketStructurePanel

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
    from scanner.tui.components import BinaryMarketStructurePanel

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
