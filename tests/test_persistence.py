"""Tests for persistence redesign: unified scans, schema migration, scan_id, CSV export."""

import csv
import tempfile

from scanner.archive import find_entry_by_rank, load_latest_archive, save_scan_unified
from scanner.export import export_scans_csv, export_trades_csv
from scanner.mispricing import MispricingResult
from scanner.paper_trading import PaperTradingDB
from scanner.reporting import ScoredCandidate, TierResult
from scanner.scoring import ScoreBreakdown
from tests.conftest import make_market

# --- Unified scan archive ---

class TestUnifiedScanArchive:
    def test_save_includes_all_tiers_with_labels(self):
        c_a = ScoredCandidate(
            market=make_market(market_id="m-a"), mispricing=MispricingResult(signal="moderate"),
            score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
        )
        c_b = ScoredCandidate(
            market=make_market(market_id="m-b"), mispricing=MispricingResult(signal="none"),
            score=ScoreBreakdown(15, 14, 12, 10, 6, total=57),
        )
        c_c = ScoredCandidate(
            market=make_market(market_id="m-c"), mispricing=MispricingResult(signal="none"),
            score=ScoreBreakdown(5, 5, 5, 3, 2, total=20),
        )
        tiers = TierResult(tier_a=[c_a], tier_b=[c_b], tier_c=[c_c])

        with tempfile.TemporaryDirectory() as d:
            scan_id = save_scan_unified(tiers, d)
            assert scan_id is not None

            data = load_latest_archive(d)
            assert len(data) == 3  # all tiers included

            # Check tier labels
            ids_tiers = {e["market_id"]: e.get("tier") for e in data}
            assert ids_tiers["m-a"] == "research"
            assert ids_tiers["m-b"] == "watchlist"
            assert ids_tiers["m-c"] == "filtered"

    def test_save_returns_scan_id(self):
        tiers = TierResult(tier_a=[], tier_b=[], tier_c=[])
        with tempfile.TemporaryDirectory() as d:
            scan_id = save_scan_unified(tiers, d)
            assert scan_id is not None
            assert len(scan_id) > 8  # timestamp string

    def test_find_by_rank_works_with_unified(self):
        c1 = ScoredCandidate(
            market=make_market(market_id="m-high"),
            score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
            mispricing=MispricingResult(signal="none"),
        )
        c2 = ScoredCandidate(
            market=make_market(market_id="m-low"),
            score=ScoreBreakdown(5, 5, 5, 3, 2, total=20),
            mispricing=MispricingResult(signal="none"),
        )
        tiers = TierResult(tier_a=[c1], tier_b=[], tier_c=[c2])

        with tempfile.TemporaryDirectory() as d:
            save_scan_unified(tiers, d)
            entry = find_entry_by_rank(1, d)
            assert entry["market_id"] == "m-high"


# --- Schema migration ---

class TestSchemaMigration:
    def test_new_db_has_structure_score_column(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = PaperTradingDB(f.name)
            t = db.mark(market_id="m1", title="T", side="yes", entry_price=0.50, beauty_score=80)
            # Should work with the column name (internal is still beauty_score)
            assert t.beauty_score == 80
            db.close()

    def test_new_db_has_scan_id_column(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = PaperTradingDB(f.name)
            t = db.mark(market_id="m1", title="T", side="yes", entry_price=0.50, scan_id="20260329_100000")
            fetched = db.get(t.id)
            assert fetched.scan_id == "20260329_100000"
            db.close()


# --- CSV export ---

class TestExportTradesCSV:
    def test_export_trades(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = PaperTradingDB(f.name)
            db.mark(market_id="m1", title="BTC 88K", side="yes", entry_price=0.42)
            db.mark(market_id="m2", title="CPI 3.5%", side="no", entry_price=0.60)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as out:
                export_trades_csv(db, out.name)

            with open(out.name, encoding="utf-8-sig") as f2:
                reader = csv.DictReader(f2)
                rows = list(reader)
            assert len(rows) == 2
            ids = {r["market_id"] for r in rows}
            assert "m1" in ids
            assert "entry_price" in rows[0]
            db.close()

    def test_export_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = PaperTradingDB(f.name)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as out:
                export_trades_csv(db, out.name)
            with open(out.name, encoding="utf-8-sig") as f2:
                content = f2.read()
            assert "market_id" in content
            db.close()


class TestExportScansCSV:
    def test_export_scans(self):
        with tempfile.TemporaryDirectory() as d:
            c = ScoredCandidate(
                market=make_market(market_id="m1", title="Test"),
                score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
                mispricing=MispricingResult(signal="none"),
            )
            save_scan_unified(TierResult(tier_a=[c], tier_b=[], tier_c=[]), d)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as out:
                export_scans_csv(d, out.name)

            with open(out.name, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["market_id"] == "m1"
