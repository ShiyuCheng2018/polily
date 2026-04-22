"""Polily — A Polymarket Monitoring Agent That Actually Works.

Public API for programmatic use (without CLI).
"""

__version__ = "0.8.5"

from polily.core.config import PolilyConfig, load_config
from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow
from polily.core.models import BookLevel, Market
from polily.scan.mispricing import MispricingResult, detect_mispricing
from polily.scan.pipeline import fetch_and_score_event
from polily.scan.reporting import ScoredCandidate
from polily.scan.scoring import ScoreBreakdown, compute_structure_score

__all__ = [
    # Core types
    "Market", "BookLevel", "PolilyConfig", "load_config", "PolilyDB",
    # Event-first schema
    "EventRow", "MarketRow",
    # Pipeline
    "fetch_and_score_event", "ScoredCandidate",
    # Scoring
    "ScoreBreakdown", "compute_structure_score",
    # Mispricing
    "MispricingResult", "detect_mispricing",
]
