"""Tests for SQLite-backed analysis store."""

from scanner.analysis_store import (
    AnalysisVersion,
    append_analysis,
    get_market_analyses,
)


def _make_version(version: int = 1, **overrides) -> AnalysisVersion:
    defaults = dict(
        version=version,
        created_at="2026-03-30T00:00:00+00:00",
        market_title="BTC above $66K?",
        yes_price_at_analysis=0.64,
        analyst_output={"objectivity_score": 85, "market_type": "crypto_threshold"},
        narrative_output={"summary": "test summary", "one_line_verdict": "verdict", "risk_flags": []},
        trigger_source="manual",
        elapsed_seconds=5.0,
    )
    defaults.update(overrides)
    return AnalysisVersion(**defaults)


def test_append_and_get(polily_db):
    v = _make_version(structure_score=72.5)
    append_analysis("0xabc", v, polily_db)
    versions = get_market_analyses("0xabc", polily_db)
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].structure_score == 72.5
    assert versions[0].market_title == "BTC above $66K?"


def test_get_empty(polily_db):
    assert get_market_analyses("0xnonexistent", polily_db) == []


def test_no_version_limit(polily_db):
    for i in range(20):
        append_analysis("0xabc", _make_version(i + 1), polily_db)
    versions = get_market_analyses("0xabc", polily_db)
    assert len(versions) == 20
    assert versions[0].version == 1
    assert versions[-1].version == 20


def test_multiple_markets(polily_db):
    append_analysis("0x1", _make_version(1), polily_db)
    append_analysis("0x2", _make_version(1), polily_db)
    append_analysis("0x1", _make_version(2), polily_db)
    assert len(get_market_analyses("0x1", polily_db)) == 2
    assert len(get_market_analyses("0x2", polily_db)) == 1


def test_dict_fields_serialized(polily_db):
    v = _make_version(
        analyst_output={"key": "value", "nested": {"a": 1}},
        narrative_output={"summary": "s", "one_line_verdict": "v", "risk_flags": [{"text": "r", "severity": "info"}]},
        score_breakdown={"liquidity": 20, "objectivity": 18},
    )
    append_analysis("0xabc", v, polily_db)
    loaded = get_market_analyses("0xabc", polily_db)
    assert loaded[0].analyst_output["nested"]["a"] == 1
    assert loaded[0].narrative_output["risk_flags"][0]["text"] == "r"
    assert loaded[0].score_breakdown["liquidity"] == 20


def test_new_fields(polily_db):
    v = _make_version(
        trigger_source="scheduled",
        watch_sequence=3,
        price_at_watch=0.55,
        structure_score=72.5,
    )
    append_analysis("0xabc", v, polily_db)
    loaded = get_market_analyses("0xabc", polily_db)[0]
    assert loaded.trigger_source == "scheduled"
    assert loaded.watch_sequence == 3
    assert loaded.price_at_watch == 0.55
    assert loaded.structure_score == 72.5

