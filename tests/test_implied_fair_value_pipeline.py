"""Integration test for AF-3: pipeline writes implied_fair_value into
markets.score_breakdown for negRisk events; non-negRisk events do NOT
get the key."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import (
    EventRow,
    MarketRow,
    upsert_event,
    upsert_market,
)
from polily.core.models import Market
from polily.scan.mispricing import MispricingResult
from polily.scan.pipeline import _update_event_scores
from polily.scan.reporting import ScoredCandidate
from polily.scan.scoring import ScoreBreakdown


def _build_market(
    market_id: str,
    event_id: str,
    yes_price: float,
    *,
    neg_risk: bool,
) -> Market:
    """Build a minimal Market domain model."""
    return Market(
        market_id=market_id,
        event_id=event_id,
        title=f"Will {market_id}?",
        outcomes=["Yes", "No"],
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 4),
        clob_token_id_yes=f"y_{market_id}",
        clob_token_id_no=f"n_{market_id}",
        neg_risk=neg_risk,
        market_type="other",
        data_fetched_at=datetime.now(UTC),
    )


def _scored(market: Market) -> ScoredCandidate:
    """Wrap a Market into a ScoredCandidate with default zero score and
    no mispricing — minimal harness for _update_event_scores."""
    score = ScoreBreakdown(
        liquidity_structure=0.0,
        objective_verifiability=0.0,
        probability_space=0.0,
        time_structure=0.0,
        trading_friction=0.0,
        net_edge=0.0,
        total=0.0,
    )
    return ScoredCandidate(
        market=market,
        score=score,
        mispricing=MispricingResult(signal="none"),
    )


@pytest.fixture
def db_with_neg_risk_event(tmp_path):
    """Seed a 3-market negRisk event + a 2-market non-negRisk event."""
    db = PolilyDB(tmp_path / "ifv_pipeline.db")

    # negRisk event with 3 markets summing to 0.9 (under-priced)
    upsert_event(
        EventRow(
            event_id="neg_evt",
            title="Three-way negRisk",
            updated_at="2026-05-07T00:00:00Z",
            neg_risk=True,
        ),
        db,
    )
    for mid, yp in [("nm1", 0.5), ("nm2", 0.3), ("nm3", 0.1)]:
        upsert_market(
            MarketRow(
                market_id=mid, event_id="neg_evt",
                question=f"Will {mid}?",
                clob_token_id_yes=f"y_{mid}", clob_token_id_no=f"n_{mid}",
                yes_price=yp, no_price=1.0 - yp,
                neg_risk=True,
                updated_at="2026-05-07T00:00:00Z",
            ),
            db,
        )

    # non-negRisk event with 2 markets — should NOT get implied_fair_value
    upsert_event(
        EventRow(
            event_id="ind_evt",
            title="Two independent",
            updated_at="2026-05-07T00:00:00Z",
            neg_risk=False,
        ),
        db,
    )
    for mid, yp in [("im1", 0.6), ("im2", 0.7)]:
        upsert_market(
            MarketRow(
                market_id=mid, event_id="ind_evt",
                question=f"Will {mid}?",
                clob_token_id_yes=f"y_{mid}", clob_token_id_no=f"n_{mid}",
                yes_price=yp, no_price=1.0 - yp,
                neg_risk=False,
                updated_at="2026-05-07T00:00:00Z",
            ),
            db,
        )

    return db


def test_pipeline_writes_implied_fair_value_for_neg_risk(db_with_neg_risk_event):
    """After the score pipeline runs, negRisk markets have
    score_breakdown.implied_fair_value populated; non-negRisk do not."""
    db = db_with_neg_risk_event

    # Build candidates list using real ScoredCandidate dataclass.
    candidates = [
        _scored(_build_market("nm1", "neg_evt", 0.5, neg_risk=True)),
        _scored(_build_market("nm2", "neg_evt", 0.3, neg_risk=True)),
        _scored(_build_market("nm3", "neg_evt", 0.1, neg_risk=True)),
        _scored(_build_market("im1", "ind_evt", 0.6, neg_risk=False)),
        _scored(_build_market("im2", "ind_evt", 0.7, neg_risk=False)),
    ]

    _update_event_scores(candidates, db)

    # Verify negRisk markets have implied_fair_value
    expected_ifv = {"nm1": 0.6, "nm2": 0.4, "nm3": 0.2}
    for mid, expected in expected_ifv.items():
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT score_breakdown FROM markets WHERE market_id = ?",
                (mid,),
            ).fetchone()
        assert row is not None, f"market {mid} missing"
        bd = json.loads(row["score_breakdown"]) if row["score_breakdown"] else {}
        assert "implied_fair_value" in bd, (
            f"negRisk market {mid} missing implied_fair_value in "
            f"score_breakdown: keys={list(bd.keys())}"
        )
        assert abs(bd["implied_fair_value"] - expected) < 1e-9, (
            f"market {mid}: implied_fair_value = {bd['implied_fair_value']}, "
            f"expected {expected}"
        )

    # Verify non-negRisk markets do NOT have implied_fair_value
    for mid in ("im1", "im2"):
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT score_breakdown FROM markets WHERE market_id = ?",
                (mid,),
            ).fetchone()
        bd = json.loads(row["score_breakdown"]) if row["score_breakdown"] else {}
        assert "implied_fair_value" not in bd, (
            f"non-negRisk market {mid} should NOT have implied_fair_value "
            f"key (explicit absence > explicit None); got bd={bd}"
        )
