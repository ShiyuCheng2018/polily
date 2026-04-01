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

    def test_old_data_with_deprecated_fields_loads(self):
        """Old stored data with removed fields should load via extra=ignore."""
        old_data = {
            "market_id": "test",
            "summary": "old analysis",
            "suggested_style": "research_candidate",
            "research_checklist": ["check BTC price"],
            "action_reasoning": "old reasoning",
        }
        out = NarrativeWriterOutput.model_validate(old_data)
        assert out.market_id == "test"


class TestSemanticValidation:
    def test_pass_requires_why_not_now(self):
        out = NarrativeWriterOutput(
            market_id="test", action="PASS",
            summary="ok summary", one_line_verdict="verdict",
        )
        errors = out.semantic_errors()
        assert any("why_not_now" in e for e in errors)

    def test_watch_requires_watch_condition(self):
        out = NarrativeWriterOutput(
            market_id="test", action="WATCH",
            why_not_now="Not enough edge after friction analysis",
            summary="ok", one_line_verdict="v",
        )
        errors = out.semantic_errors()
        assert any("watch" in e.lower() for e in errors)

    def test_complete_pass_no_errors(self):
        out = NarrativeWriterOutput(
            market_id="test", action="PASS",
            why_not_now="No edge visible, friction dominates.",
            summary="Market efficiently priced, no action.",
            one_line_verdict="PASS: no edge.",
            invalidation_findings=[ResearchFinding(finding="f", source="s", impact="i")],
        )
        assert out.semantic_errors() == []

    def test_missing_summary_flagged(self):
        out = NarrativeWriterOutput(
            market_id="test", action="PASS",
            why_not_now="Good reason not to trade this market.",
        )
        errors = out.semantic_errors()
        assert any("summary" in e for e in errors)

    def test_watch_requires_next_check_at(self):
        out = NarrativeWriterOutput(
            market_id="test", action="WATCH",
            watch=WatchCondition(
                watch_reason="test",
                next_check_at="2026-04-05T20:00:00",
                reason="tariff announcement",
            ),
            why_not_now="waiting for catalyst to materialize",
            invalidation_findings=[ResearchFinding(finding="x", source="y", impact="z")],
            summary="test summary here",
            one_line_verdict="test verdict",
        )
        assert len(out.semantic_errors()) == 0

    def test_watch_without_next_check_at_is_error(self):
        out = NarrativeWriterOutput(
            market_id="test", action="WATCH",
            watch=WatchCondition(watch_reason="test"),
            why_not_now="waiting for something to happen",
            invalidation_findings=[ResearchFinding(finding="x", source="y", impact="z")],
            summary="test summary", one_line_verdict="test verdict",
        )
        errors = out.semantic_errors()
        assert any("next_check_at" in e for e in errors)

    def test_pass_must_not_have_watch_conditions(self):
        out = NarrativeWriterOutput(
            market_id="test", action="PASS",
            watch=WatchCondition(watch_reason="should not be here"),
            why_not_now="not worth it at all",
            invalidation_findings=[ResearchFinding(finding="x", source="y", impact="z")],
            summary="test summary", one_line_verdict="test verdict",
        )
        errors = out.semantic_errors()
        assert any("PASS" in e for e in errors)

    def test_watch_condition_has_new_fields(self):
        wc = WatchCondition(
            watch_reason="price not right",
            better_entry="YES <= 0.50",
            next_check_at="2026-04-05T20:00:00",
            reason="tariff announcement expected that evening",
        )
        assert wc.next_check_at == "2026-04-05T20:00:00"
        assert wc.reason == "tariff announcement expected that evening"
