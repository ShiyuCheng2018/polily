"""Tests for SQLite-backed analysis store."""

import json
import tempfile
from pathlib import Path

from scanner.analysis_store import (
    AnalysisVersion,
    append_analysis,
    build_previous_context,
    get_market_analyses,
)
from scanner.db import PolilyDB


def _make_db():
    tmp = tempfile.mkdtemp()
    return PolilyDB(Path(tmp) / "polily.db")


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


def test_append_and_get():
    db = _make_db()
    v = _make_version(structure_score=72.5)
    append_analysis("0xabc", v, db)
    versions = get_market_analyses("0xabc", db)
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].structure_score == 72.5
    assert versions[0].market_title == "BTC above $66K?"
    db.close()


def test_get_empty():
    db = _make_db()
    assert get_market_analyses("0xnonexistent", db) == []
    db.close()


def test_no_version_limit():
    db = _make_db()
    for i in range(20):
        append_analysis("0xabc", _make_version(i + 1), db)
    versions = get_market_analyses("0xabc", db)
    assert len(versions) == 20
    assert versions[0].version == 1
    assert versions[-1].version == 20
    db.close()


def test_multiple_markets():
    db = _make_db()
    append_analysis("0x1", _make_version(1), db)
    append_analysis("0x2", _make_version(1), db)
    append_analysis("0x1", _make_version(2), db)
    assert len(get_market_analyses("0x1", db)) == 2
    assert len(get_market_analyses("0x2", db)) == 1
    db.close()


def test_dict_fields_serialized():
    db = _make_db()
    v = _make_version(
        analyst_output={"key": "value", "nested": {"a": 1}},
        narrative_output={"summary": "s", "one_line_verdict": "v", "risk_flags": [{"text": "r", "severity": "info"}]},
        score_breakdown={"liquidity": 20, "objectivity": 18},
    )
    append_analysis("0xabc", v, db)
    loaded = get_market_analyses("0xabc", db)
    assert loaded[0].analyst_output["nested"]["a"] == 1
    assert loaded[0].narrative_output["risk_flags"][0]["text"] == "r"
    assert loaded[0].score_breakdown["liquidity"] == 20
    db.close()


def test_new_fields():
    db = _make_db()
    v = _make_version(
        trigger_source="scheduled",
        watch_sequence=3,
        price_at_watch=0.55,
        structure_score=72.5,
    )
    append_analysis("0xabc", v, db)
    loaded = get_market_analyses("0xabc", db)[0]
    assert loaded.trigger_source == "scheduled"
    assert loaded.watch_sequence == 3
    assert loaded.price_at_watch == 0.55
    assert loaded.structure_score == 72.5
    db.close()


def test_build_previous_context_full_history():
    db = _make_db()
    for i in range(3):
        v = _make_version(
            version=i + 1,
            created_at=f"2026-04-0{i + 1}T10:00:00",
            yes_price_at_analysis=0.65 - i * 0.05,
            narrative_output={
                "summary": f"summary_{i}",
                "one_line_verdict": f"verdict_{i}",
                "risk_flags": [],
                "action": "WATCH" if i < 2 else "BUY_YES",
            },
        )
        append_analysis("0xabc", v, db)
    ctx = build_previous_context(get_market_analyses("0xabc", db))
    assert ctx is not None
    # All 3 versions should appear
    assert "verdict_0" in ctx
    assert "verdict_1" in ctx
    assert "verdict_2" in ctx
    # Prices should appear
    assert "0.65" in ctx
    assert "0.55" in ctx
    db.close()


def test_build_previous_context_empty():
    assert build_previous_context([]) is None
