"""Polily — Polymarket Decision Copilot.

Public API for programmatic use (without CLI).
"""

__version__ = "0.5.0"

from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow
from scanner.core.models import BookLevel, Market
from scanner.scan.filters import FilterResult, apply_hard_filters
from scanner.scan.mispricing import MispricingResult, detect_mispricing
from scanner.scan.pipeline import run_scan_pipeline
from scanner.scan.reporting import ScoredCandidate, TierResult
from scanner.scan.scoring import ScoreBreakdown, compute_structure_score
from scanner.scan.tag_classifier import classify_from_tags

__all__ = [
    # Core types
    "Market", "BookLevel", "ScannerConfig", "load_config", "PolilyDB",
    # Event-first schema
    "EventRow", "MarketRow",
    # Pipeline
    "run_scan_pipeline", "ScoredCandidate", "TierResult",
    # Scoring
    "ScoreBreakdown", "compute_structure_score",
    # Mispricing
    "MispricingResult", "detect_mispricing",
    # Filters
    "apply_hard_filters", "FilterResult",
    # Classification
    "classify_from_tags",
]
