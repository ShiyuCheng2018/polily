"""Tests for Phase 1 schema changes — new decision-oriented fields."""

from scanner.agents.schemas import (
    BiasOutput,
    NarrativeWriterOutput,
    ResearchFinding,
    RiskFlag,
    TimeWindow,
)


class TestNewTypes:
    def test_time_window(self):
        tw = TimeWindow(urgency="urgent", note="还剩 1.2 天")
        assert tw.urgency == "urgent"
        assert tw.optimal_entry is None

    def test_time_window_with_entry(self):
        tw = TimeWindow(urgency="normal", note="3天后结算", optimal_entry="CPI 发布前入场")
        assert tw.optimal_entry == "CPI 发布前入场"

    def test_risk_flag(self):
        rf = RiskFlag(text="摩擦吃掉 80% 利润", severity="critical")
        assert rf.severity == "critical"

    def test_research_finding(self):
        rf = ResearchFinding(
            finding="BTC 过去 24h 下跌 3.2%",
            source="Binance",
            impact="距离阈值更远",
        )
        assert rf.source == "Binance"

    def test_bias_output(self):
        b = BiasOutput(
            direction="lean_yes",
            reasoning="模型估值 0.45",
            confidence="medium",
            caveat="前提是 BTC 维持波动率",
        )
        assert b.direction == "lean_yes"


class TestNarrativeWriterOutputV2:
    def test_new_fields_present(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="watch_only",
            action_reasoning="摩擦太高",
            confidence="medium",
            time_window=TimeWindow(urgency="normal", note="2天"),
            friction_impact="摩擦吃掉 65% 利润",
            summary="测试总结",
            risk_flags=[RiskFlag(text="高风险", severity="critical")],
            counterparty_note="对手方是 bot",
            research_findings=[
                ResearchFinding(finding="BTC $67k", source="Binance", impact="接近阈值"),
            ],
            one_line_verdict="watch_only: 好市场但价格不对",
        )
        assert out.action == "watch_only"
        assert out.time_window.urgency == "normal"
        assert len(out.research_findings) == 1
        assert out.risk_flags[0].severity == "critical"
        assert out.bias is None  # optional

    def test_with_bias(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="small_position_ok",
            action_reasoning="有 edge",
            confidence="high",
            time_window=TimeWindow(urgency="urgent", note="1天"),
            friction_impact="摩擦吃掉 20% 利润",
            summary="总结",
            risk_flags=[],
            counterparty_note="",
            research_findings=[],
            one_line_verdict="可以小仓位",
            bias=BiasOutput(
                direction="lean_yes", reasoning="低估",
                confidence="medium", caveat="前提...",
            ),
        )
        assert out.bias.direction == "lean_yes"

    def test_model_dump_roundtrip(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="avoid",
            action_reasoning="没有 edge",
            confidence="low",
            time_window=TimeWindow(urgency="no_rush", note="7天"),
            friction_impact="无可测量 edge",
            summary="不值得",
            risk_flags=[RiskFlag(text="无 edge", severity="warning")],
            counterparty_note="",
            research_findings=[],
            one_line_verdict="avoid",
        )
        data = out.model_dump()
        restored = NarrativeWriterOutput.model_validate(data)
        assert restored.action == "avoid"
        assert restored.risk_flags[0].severity == "warning"
