"""Polily — Polymarket Decision Copilot.

Public API for programmatic use (without CLI).
"""

__version__ = "0.6.1"

from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow
from scanner.core.models import BookLevel, Market
from scanner.scan.mispricing import MispricingResult, detect_mispricing
from scanner.scan.pipeline import fetch_and_score_event
from scanner.scan.reporting import ScoredCandidate
from scanner.scan.scoring import ScoreBreakdown, compute_structure_score

__all__ = [
    # Core types
    "Market", "BookLevel", "ScannerConfig", "load_config", "PolilyDB",
    # Event-first schema
    "EventRow", "MarketRow",
    # Pipeline
    "fetch_and_score_event", "ScoredCandidate",
    # Scoring
    "ScoreBreakdown", "compute_structure_score",
    # Mispricing
    "MispricingResult", "detect_mispricing",
]
