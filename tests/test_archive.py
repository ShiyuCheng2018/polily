"""Tests for scan archive save/load/query functions."""

import json
import tempfile
from pathlib import Path

from scanner.archive import (
    find_entry_by_rank,
    find_entry_in_archive,
    load_demo_data,
    load_latest_archive,
    save_scan_unified,
)
from scanner.mispricing import MispricingResult
from scanner.reporting import ScoredCandidate, TierResult
from scanner.scoring import ScoreBreakdown
from tests.conftest import make_market


def _make_tiers():
    c1 = ScoredCandidate(
        market=make_market(market_id="m-high", title="High"),
        score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
        mispricing=MispricingResult(signal="moderate"),
    )
    c2 = ScoredCandidate(
        market=make_market(market_id="m-mid", title="Mid"),
        score=ScoreBreakdown(15, 14, 12, 10, 6, total=57),
        mispricing=MispricingResult(signal="none"),
    )
    return TierResult(tier_a=[c1], tier_b=[c2], tier_c=[])


class TestSaveAndLoad:
    def test_save_and_load_json(self):
        with tempfile.TemporaryDirectory() as d:
            tiers = _make_tiers()
            scan_id = save_scan_unified(tiers, d)
            path = Path(d) / f"{scan_id}.json"
            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 2

    def test_save_archive_includes_all_with_tier_labels(self):
        """Unified archive includes all tiers with tier labels."""
        with tempfile.TemporaryDirectory() as d:
            tiers = TierResult(
                tier_a=[_make_tiers().tier_a[0]],
                tier_b=[_make_tiers().tier_b[0]],
                tier_c=[ScoredCandidate(
                    market=make_market(market_id="m-bad"),
                    score=ScoreBreakdown(5, 5, 5, 3, 2, total=20),
                    mispricing=MispricingResult(signal="none"),
                )],
            )
            save_scan_unified(tiers, d)
            data = load_latest_archive(d)
            ids_tiers = {e["market_id"]: e.get("tier") for e in data}
            assert "m-high" in ids_tiers
            assert ids_tiers.get("m-bad") == "filtered"  # Tier C now included with label


class TestFindEntry:
    def test_find_by_market_id(self):
        with tempfile.TemporaryDirectory() as d:
            save_scan_unified(_make_tiers(), d)
            entry = find_entry_in_archive("m-high", d)
            assert entry is not None
            assert entry["market_id"] == "m-high"

    def test_find_nonexistent(self):
        with tempfile.TemporaryDirectory() as d:
            save_scan_unified(_make_tiers(), d)
            assert find_entry_in_archive("doesnt-exist", d) is None

    def test_find_by_rank(self):
        with tempfile.TemporaryDirectory() as d:
            save_scan_unified(_make_tiers(), d)
            entry = find_entry_by_rank(1, d)
            assert entry is not None
            assert entry["structure_score"] == 74  # highest score

    def test_rank_out_of_range(self):
        with tempfile.TemporaryDirectory() as d:
            save_scan_unified(_make_tiers(), d)
            assert find_entry_by_rank(999, d) is None

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            assert load_latest_archive(d) is None
            assert find_entry_in_archive("x", d) is None
            assert find_entry_by_rank(1, d) is None


class TestDemoData:
    def test_load_missing(self):
        markets = load_demo_data("/nonexistent/path.json")
        assert markets == []
