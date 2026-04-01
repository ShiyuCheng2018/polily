"""Tests for analysis store persistence."""

import tempfile
from pathlib import Path

from scanner.analysis_store import (
    AnalysisVersion,
    append_analysis,
    get_market_analyses,
    load_analyses,
    save_analyses,
)


def _make_version(version: int = 1) -> AnalysisVersion:
    return AnalysisVersion(
        version=version,
        created_at="2026-03-30T00:00:00+00:00",
        market_title="BTC above $66K?",
        yes_price_at_analysis=0.64,
        analyst_output={"objectivity_score": 85, "market_type": "crypto_threshold"},
        narrative_output={"summary": "test", "risk_flags": []},
        elapsed_seconds=5.0,
    )


class TestAnalysisStore:
    def test_load_nonexistent(self):
        assert load_analyses("/nonexistent/path.json") == {}

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            data = {"m1": [_make_version().model_dump()]}
            save_analyses(data, path)
            loaded = load_analyses(path)
            assert "m1" in loaded
            assert len(loaded["m1"]) == 1

    def test_get_market_analyses(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            v = _make_version()
            save_analyses({"m1": [v.model_dump()]}, path)
            versions = get_market_analyses("m1", path)
            assert len(versions) == 1
            assert versions[0].version == 1

    def test_get_market_analyses_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            assert get_market_analyses("nonexistent", path) == []

    def test_append_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            append_analysis("m1", _make_version(1), path)
            append_analysis("m1", _make_version(2), path)
            versions = get_market_analyses("m1", path)
            assert len(versions) == 2
            assert versions[0].version == 1
            assert versions[1].version == 2

    def test_append_truncates_to_max(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            for i in range(15):
                append_analysis("m1", _make_version(i + 1), path, max_versions=5)
            versions = get_market_analyses("m1", path)
            assert len(versions) == 5
            assert versions[0].version == 11  # kept last 5

    def test_multiple_markets(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "analyses.json"
            append_analysis("m1", _make_version(1), path)
            append_analysis("m2", _make_version(1), path)
            assert len(get_market_analyses("m1", path)) == 1
            assert len(get_market_analyses("m2", path)) == 1
