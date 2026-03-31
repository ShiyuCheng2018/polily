"""Tests for decision assistant schema."""

from scanner.agents.schemas import (
    CryptoContext,
    NarrativeWriterOutput,
    ResearchFinding,
    RiskFlag,
    TimeWindow,
    WatchCondition,
)


class TestNewTypes:
    def test_time_window(self):
        tw = TimeWindow(urgency="urgent", note="还剩 1.2 天")
        assert tw.urgency == "urgent"
        assert tw.optimal_entry is None

    def test_risk_flag(self):
        rf = RiskFlag(text="摩擦吃掉 80% 利润", severity="critical")
        assert rf.severity == "critical"

    def test_research_finding(self):
        rf = ResearchFinding(finding="BTC 下跌 3.2%", source="Binance", impact="距离阈值更远")
        assert rf.source == "Binance"

    def test_crypto_context(self):
        cc = CryptoContext(
            distance_to_threshold_pct=1.2, buffer_pct=1.2,
            daily_vol_pct=3.5, buffer_conclusion="thin",
            market_already_knows="定价已反映 CPI 预期",
        )
        assert cc.buffer_conclusion == "thin"

    def test_watch_condition(self):
        wc = WatchCondition(watch_reason="价格不对", better_entry="YES <= 0.58")
        assert wc.better_entry == "YES <= 0.58"


class TestNarrativeWriterOutputV3:
    def test_new_decision_fields(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="WATCH",
            bias="YES",
            strength="medium",
            confidence="medium",
            opportunity_type="watch_only",
            why_now="",
            why_not_now="摩擦太高",
            friction_vs_edge="friction_exceeds",
            execution_risk="low",
            summary="测试",
        )
        assert out.action == "WATCH"
        assert out.bias == "YES"
        assert out.friction_vs_edge == "friction_exceeds"

    def test_with_crypto_context(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="BUY_YES",
            bias="YES",
            strength="strong",
            confidence="high",
            opportunity_type="instant_mispricing",
            summary="有 edge",
            crypto=CryptoContext(
                distance_to_threshold_pct=5.2,
                buffer_pct=5.2,
                daily_vol_pct=3.5,
                buffer_conclusion="adequate",
                market_already_knows="",
            ),
        )
        assert out.crypto.buffer_conclusion == "adequate"
        assert out.action == "BUY_YES"

    def test_supporting_and_invalidation_findings(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="PASS",
            summary="不值得",
            supporting_findings=[
                ResearchFinding(finding="支持", source="A", impact="正面"),
            ],
            invalidation_findings=[
                ResearchFinding(finding="反驳", source="B", impact="可能推翻"),
            ],
        )
        assert len(out.supporting_findings) == 1
        assert len(out.invalidation_findings) == 1

    def test_model_dump_roundtrip(self):
        out = NarrativeWriterOutput(
            market_id="test",
            action="PASS",
            summary="不值得",
            risk_flags=[RiskFlag(text="高摩擦", severity="critical")],
            next_step="pass_for_now",
        )
        data = out.model_dump()
        restored = NarrativeWriterOutput.model_validate(data)
        assert restored.action == "PASS"
        assert restored.next_step == "pass_for_now"

    def test_backward_compat_defaults(self):
        """Old data with minimal fields should still validate."""
        out = NarrativeWriterOutput(market_id="test", summary="old format")
        assert out.action == "PASS"
        assert out.bias == "NONE"
        assert out.crypto is None
