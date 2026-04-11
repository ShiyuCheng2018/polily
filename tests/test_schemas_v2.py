"""Tests for decision assistant schema."""

from scanner.agents.schemas import (
    CryptoContext,
    NarrativeWriterOutput,
    ResearchFinding,
    RiskFlag,
    TimeWindow,
)


# Helper: minimal valid output for a given action
def _valid_output(**overrides) -> NarrativeWriterOutput:
    defaults = {
        "event_id": "test",
        "action": "PASS",
        "why_not": "No edge visible, friction dominates.",
        "summary": "Market efficiently priced, no action.",
        "one_line_verdict": "PASS: no edge.",
        "invalidation_findings": [ResearchFinding(finding="f", source="s", impact="i")],
        "next_check_at": "2026-04-10T12:00:00",
        "next_check_reason": "default check",
    }
    defaults.update(overrides)
    return NarrativeWriterOutput(**defaults)


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


class TestNarrativeWriterOutputV3:
    def test_new_decision_fields(self):
        out = _valid_output(action="WATCH",
                            confidence="medium",
                            why="", why_not="摩擦太高",
                            friction_vs_edge="friction_exceeds")
        assert out.action == "WATCH"
        assert out.friction_vs_edge == "friction_exceeds"

    def test_with_crypto_context(self):
        out = _valid_output(
            action="BUY_YES",
            confidence="high",
            why="Strong edge detected",
            why_not="",
            summary="有 edge",
            crypto=CryptoContext(
                distance_to_threshold_pct=5.2, buffer_pct=5.2,
                daily_vol_pct=3.5, buffer_conclusion="adequate",
            ),
            supporting_findings=[ResearchFinding(finding="x", source="y", impact="z")],
        )
        assert out.crypto.buffer_conclusion == "adequate"
        assert out.action == "BUY_YES"

    def test_supporting_and_invalidation_findings(self):
        out = _valid_output(
            supporting_findings=[ResearchFinding(finding="支持", source="A", impact="正面")],
            invalidation_findings=[ResearchFinding(finding="反驳", source="B", impact="可能推翻")],
        )
        assert len(out.supporting_findings) == 1
        assert len(out.invalidation_findings) == 1

    def test_model_dump_roundtrip(self):
        out = _valid_output(
            risk_flags=[RiskFlag(text="高摩擦", severity="critical")],
        )
        data = out.model_dump()
        restored = NarrativeWriterOutput.model_validate(data)
        assert restored.action == "PASS"

    def test_backward_compat_defaults(self):
        """Old data with minimal fields should still validate."""
        out = NarrativeWriterOutput(event_id="test", summary="old format")
        assert out.action == "PASS"
        assert out.crypto is None

    def test_old_data_with_deprecated_fields_loads(self):
        """Old stored data with removed fields should load via extra=ignore."""
        old_data = {
            "event_id": "test",
            "summary": "old analysis",
            "suggested_style": "research_candidate",
            "research_checklist": ["check BTC price"],
            "action_reasoning": "old reasoning",
            "watch": {"watch_reason": "old watch", "next_check_at": "2026-04-05"},
        }
        out = NarrativeWriterOutput.model_validate(old_data)
        assert out.event_id == "test"

    def test_event_id_field_exists(self):
        """event_id field replaces market_id."""
        out = NarrativeWriterOutput(event_id="ev1", summary="test")
        assert out.event_id == "ev1"
        assert "market_id" not in NarrativeWriterOutput.model_fields

    def test_old_market_id_data_ignored(self):
        """Old stored data with market_id should load via extra=ignore (field gone)."""
        old_data = {
            "market_id": "old_id",
            "event_id": "ev1",
            "summary": "migrated",
        }
        out = NarrativeWriterOutput.model_validate(old_data)
        assert out.event_id == "ev1"

    def test_next_check_at_on_output(self):
        out = _valid_output(next_check_at="2026-04-10T12:00:00",
                            next_check_reason="BOM data release")
        assert out.next_check_at == "2026-04-10T12:00:00"
        assert out.next_check_reason == "BOM data release"


class TestSemanticValidation:
    def test_pass_requires_why_not(self):
        out = NarrativeWriterOutput(
            event_id="test", action="PASS",
            summary="ok summary", one_line_verdict="verdict",
            next_check_at="2026-04-10T12:00:00",
        )
        errors = out.semantic_errors()
        assert any("why_not" in e for e in errors)

    def test_watch_requires_why_not(self):
        out = _valid_output(action="WATCH", why_not="")
        errors = out.semantic_errors()
        assert any("why_not" in e for e in errors)

    def test_complete_pass_no_errors(self):
        out = _valid_output()
        assert out.semantic_errors() == []

    def test_complete_buy_no_errors(self):
        out = _valid_output(
            action="BUY_YES",
            why="Strong edge with clear catalyst detected",
            why_not="",
            recommended_market_id="0xtest",
            supporting_findings=[ResearchFinding(finding="f", source="s", impact="i")],
            invalidation_findings=[ResearchFinding(finding="f", source="s", impact="i")],
        )
        assert out.semantic_errors() == []

    def test_missing_summary_flagged(self):
        out = _valid_output(summary="")
        errors = out.semantic_errors()
        assert any("summary" in e for e in errors)

    def test_next_check_at_required_for_all_actions(self):
        """next_check_at is required for every action."""
        for action in ("BUY_YES", "BUY_NO", "WATCH", "PASS", "HOLD", "SELL_YES", "REDUCE_YES"):
            kwargs = {"action": action, "next_check_at": None}
            if action in ("BUY_YES", "BUY_NO"):
                kwargs["why"] = "Strong edge detected here"
                kwargs["why_not"] = ""
                kwargs["supporting_findings"] = [ResearchFinding(finding="f", source="s", impact="i")]
                kwargs["recommended_market_id"] = "0xtest"
                kwargs["invalidation_findings"] = [ResearchFinding(finding="f", source="s", impact="i")]
            elif action in ("HOLD", "SELL_YES", "REDUCE_YES"):
                kwargs["mode"] = "position_management"
                kwargs["thesis_status"] = "broken" if "SELL" in action else "intact"
                kwargs["why"] = "Position management reason here"
                kwargs["why_not"] = ""
                if "SELL" in action:
                    kwargs["invalidation_findings"] = [ResearchFinding(finding="f", source="s", impact="i")]
            out = _valid_output(**kwargs)
            errors = out.semantic_errors()
            assert any("next_check_at" in e for e in errors), f"{action} should require next_check_at"

    def test_next_check_at_present_passes(self):
        out = _valid_output(next_check_at="2026-04-10T12:00:00")
        errors = out.semantic_errors()
        assert not any("next_check_at" in e for e in errors)

    def test_watch_field_no_longer_exists(self):
        """WatchCondition and watch field removed from schema."""
        assert "watch" not in NarrativeWriterOutput.model_fields


class TestPositionActions:
    def test_hold_action_valid(self):
        out = _valid_output(action="HOLD", mode="position_management",
                            thesis_status="intact",
                            why="Thesis intact, BTC above threshold", why_not="")
        assert out.semantic_errors() == []

    def test_sell_action_valid(self):
        out = _valid_output(action="SELL_YES", mode="position_management",
                            thesis_status="broken",
                            why="Thesis broken, recommend exit", why_not="",
                            invalidation_findings=[ResearchFinding(finding="f", source="s", impact="i")])
        assert out.semantic_errors() == []

    def test_reduce_action_valid(self):
        out = _valid_output(action="REDUCE_YES", mode="position_management",
                            thesis_status="weakened",
                            why="Edge narrowing, take partial profit", why_not="")
        assert out.semantic_errors() == []

    def test_hold_requires_why(self):
        out = _valid_output(action="HOLD", mode="position_management",
                            thesis_status="intact",
                            why="", why_not="")
        errors = out.semantic_errors()
        assert any("why" in e for e in errors)

    def test_sell_requires_invalidation(self):
        """SELL_YES without invalidation_findings should error."""
        out = _valid_output(action="SELL_YES", mode="position_management",
                            thesis_status="broken",
                            why="Thesis broken completely", why_not="",
                            invalidation_findings=[])
        errors = out.semantic_errors()
        assert any("invalidation" in e.lower() for e in errors)

    def test_sell_requires_why(self):
        out = _valid_output(action="SELL_YES", mode="position_management",
                            thesis_status="broken",
                            why="", why_not="",
                            invalidation_findings=[ResearchFinding(finding="f", source="s", impact="i")])
        errors = out.semantic_errors()
        assert any("why" in e for e in errors)
