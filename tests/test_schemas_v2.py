"""Tests for decision assistant schema."""

from scanner.agents.schemas import (
    CryptoContext,
    NarrativeWriterOutput,
    Operation,
    ResearchFinding,
    RiskFlag,
    TimeWindow,
)


# Helper: minimal valid output for a given mode
def _valid_output(**overrides) -> NarrativeWriterOutput:
    defaults = {
        "event_id": "test",
        "summary": "Market efficiently priced, no action.",
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

    def test_operation(self):
        op = Operation(action="BUY_YES", market_id="0xabc", reasoning="Strong edge")
        assert op.action == "BUY_YES"
        assert op.market_id == "0xabc"
        assert op.entry_price is None


class TestNarrativeWriterOutputV4:
    def test_empty_operations_is_valid(self):
        out = _valid_output()
        assert out.operations == []
        assert out.semantic_errors() == []

    def test_single_operation(self):
        out = _valid_output(
            operations=[Operation(
                action="BUY_YES", market_id="0xtest",
                market_title="BTC > $80K",
                entry_price=0.65, position_size_usd=20,
                reasoning="Strong edge detected",
            )],
            confidence="high",
        )
        assert len(out.operations) == 1
        assert out.operations[0].action == "BUY_YES"
        assert out.semantic_errors() == []

    def test_multiple_operations(self):
        out = _valid_output(
            operations=[
                Operation(action="BUY_YES", reasoning="Main play"),
                Operation(action="BUY_NO", reasoning="Hedge"),
            ],
        )
        assert len(out.operations) == 2
        assert out.semantic_errors() == []

    def test_modular_content(self):
        out = _valid_output(
            analysis="BTC approaching threshold",
            analysis_commentary="Looks bullish",
            research_commentary="Research is mixed",
            risk_commentary="Low risk overall",
            operations_commentary="Simple directional play",
        )
        assert out.analysis_commentary == "Looks bullish"
        assert out.research_commentary == "Research is mixed"

    def test_research_findings(self):
        out = _valid_output(
            research_findings=[
                ResearchFinding(finding="CPI低于预期", source="CoinDesk", impact="BTC上涨"),
                ResearchFinding(finding="ETF流入", source="Bloomberg", impact="机构买盘"),
            ],
        )
        assert len(out.research_findings) == 2

    def test_model_dump_roundtrip(self):
        out = _valid_output(
            risk_flags=[RiskFlag(text="高摩擦", severity="critical")],
        )
        data = out.model_dump()
        restored = NarrativeWriterOutput.model_validate(data)
        assert restored.confidence == "low"

    def test_backward_compat_defaults(self):
        """Old data with minimal fields should still validate."""
        out = NarrativeWriterOutput(event_id="test", summary="old format")
        assert out.operations == []
        assert out.confidence == "low"

    def test_old_data_with_deprecated_fields_loads(self):
        """Old stored data with removed fields should load via extra=ignore."""
        old_data = {
            "event_id": "test",
            "summary": "old analysis",
            "action": "WATCH",
            "why": "old reasoning",
            "why_not": "old why not",
            "one_line_verdict": "old verdict",
            "recommended_market_id": "0xtest",
            "friction_vs_edge": "edge_exceeds",
            "counterparty_note": "bots heavy",
            "event_overview": "overview",
            "recheck_conditions": ["check price"],
            "current_pnl_note": "up 10%",
            "crypto": {"distance_to_threshold_pct": 1.2},
            "direction": "YES",
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
    def test_operation_missing_reasoning_flagged(self):
        out = _valid_output(
            operations=[Operation(action="BUY_YES", reasoning="")],
        )
        errors = out.semantic_errors()
        assert any("reasoning" in e for e in errors)

    def test_operation_missing_action_flagged(self):
        out = _valid_output(
            operations=[Operation(action="", reasoning="some reason")],
        )
        errors = out.semantic_errors()
        assert any("action" in e for e in errors)

    def test_valid_operation_no_errors(self):
        out = _valid_output(
            operations=[Operation(action="BUY_YES", reasoning="Strong edge")],
        )
        assert out.semantic_errors() == []

    def test_missing_summary_flagged(self):
        out = _valid_output(summary="")
        errors = out.semantic_errors()
        assert any("summary" in e for e in errors)

    def test_next_check_at_required(self):
        out = _valid_output(next_check_at=None)
        errors = out.semantic_errors()
        assert any("next_check_at" in e for e in errors)

    def test_next_check_at_present_passes(self):
        out = _valid_output(next_check_at="2026-04-10T12:00:00")
        errors = out.semantic_errors()
        assert not any("next_check_at" in e for e in errors)

    def test_complete_output_no_errors(self):
        out = _valid_output()
        assert out.semantic_errors() == []

    def test_watch_field_no_longer_exists(self):
        """WatchCondition and watch field removed from schema."""
        assert "watch" not in NarrativeWriterOutput.model_fields


class TestPositionMode:
    def test_position_requires_thesis_status(self):
        out = _valid_output(mode="position_management", thesis_status=None)
        errors = out.semantic_errors()
        assert any("thesis_status" in e for e in errors)

    def test_position_with_thesis_status_valid(self):
        out = _valid_output(
            mode="position_management",
            thesis_status="intact",
            thesis_note="Still above threshold",
            operations=[Operation(action="HOLD", reasoning="Thesis intact")],
        )
        assert out.semantic_errors() == []

    def test_sell_operation_valid(self):
        out = _valid_output(
            mode="position_management",
            thesis_status="broken",
            operations=[Operation(action="SELL_YES", reasoning="Thesis broken, exit")],
        )
        assert out.semantic_errors() == []

    def test_reduce_operation_valid(self):
        out = _valid_output(
            mode="position_management",
            thesis_status="weakened",
            operations=[Operation(action="REDUCE_YES", reasoning="Edge narrowing")],
        )
        assert out.semantic_errors() == []

    def test_position_fields(self):
        out = _valid_output(
            mode="position_management",
            thesis_status="intact",
            thesis_note="BTC above threshold",
            stop_loss=0.25,
            take_profit=0.85,
            alternative_market_id="0xalt",
            alternative_note="Better strike",
        )
        assert out.stop_loss == 0.25
        assert out.take_profit == 0.85
        assert out.alternative_market_id == "0xalt"
