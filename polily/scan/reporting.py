"""Reporting: tier classification, JSON/terminal output."""

import json
from dataclasses import dataclass, field

from polily.core.config import ScoringThresholds
from polily.core.models import Market
from polily.scan.mispricing import MispricingResult
from polily.scan.scoring import ScoreBreakdown


@dataclass
class ScoredCandidate:
    market: Market
    score: ScoreBreakdown
    mispricing: MispricingResult
    narrative: object | None = None  # NarrativeWriterOutput when AI enabled


@dataclass
class TierResult:
    tier_a: list[ScoredCandidate] = field(default_factory=list)
    tier_b: list[ScoredCandidate] = field(default_factory=list)
    tier_c: list[ScoredCandidate] = field(default_factory=list)


def classify_tiers(
    candidates: list[ScoredCandidate],
    thresholds: ScoringThresholds,
) -> TierResult:
    """Classify scored candidates into Tier A/B/C."""
    result = TierResult()

    for c in candidates:
        score = c.score.total
        has_mispricing = c.mispricing.signal not in ("none",)

        if score >= thresholds.tier_a_min_score:
            if not thresholds.tier_a_require_mispricing or has_mispricing:
                result.tier_a.append(c)
            else:
                result.tier_b.append(c)
        elif score >= thresholds.tier_b_min_score:
            result.tier_b.append(c)
        else:
            result.tier_c.append(c)

    result.tier_a.sort(key=lambda c: c.score.total, reverse=True)
    result.tier_b.sort(key=lambda c: c.score.total, reverse=True)
    return result


def render_candidate_json(candidate: ScoredCandidate) -> str:
    """Render a single candidate as JSON string."""
    m = candidate.market
    s = candidate.score
    mp = candidate.mispricing

    data = {
        "market_id": m.market_id,
        "event_slug": m.event_slug,
        "market_slug": m.market_slug,
        "title": m.title,
        "description": m.description,
        "rules": m.rules,
        "category": m.category,
        "market_type": m.market_type,
        "tags": m.tags,
        "yes_price": m.yes_price,
        "no_price": m.no_price,
        "best_bid_yes": m.best_bid_yes,
        "best_ask_yes": m.best_ask_yes,
        "spread_yes": m.spread_yes,
        "spread_pct_yes": m.spread_pct_yes,
        "round_trip_friction_pct": m.round_trip_friction_pct,
        "volume": m.volume,
        "open_interest": m.open_interest,
        "resolution_time": m.resolution_time.isoformat() if m.resolution_time else None,
        "days_to_resolution": m.days_to_resolution,
        "total_bid_depth_usd": m.total_bid_depth_usd,
        "total_ask_depth_usd": m.total_ask_depth_usd,
        "is_binary": m.is_binary,
        "resolution_source": m.resolution_source,
        "clob_token_id_yes": m.clob_token_id_yes,
        "condition_id": m.condition_id,
        "structure_score": s.total,
        "structure_score_breakdown": {
            "liquidity_structure": s.liquidity_structure,
            "objective_verifiability": s.objective_verifiability,
            "probability_space": s.probability_space,
            "time_structure": s.time_structure,
            "trading_friction": s.trading_friction,
        },
        "mispricing_signal": mp.signal,
        "mispricing_direction": mp.direction,
        "theoretical_fair_value": mp.theoretical_fair_value,
        "mispricing_deviation_pct": mp.deviation_pct,
        "mispricing_details": mp.details,
    }

    # Include AI narrative if available
    n = candidate.narrative
    if n is not None:
        if hasattr(n, "model_dump"):
            data["narrative"] = n.model_dump()
        elif isinstance(n, dict):
            data["narrative"] = n
        else:
            data["narrative"] = {"summary": str(n)}

    return json.dumps(data, indent=2, default=str)
