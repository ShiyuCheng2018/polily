"""Polily — Polymarket research assistant.

Public API for programmatic use (without CLI).
"""

__version__ = "0.1.0"

from scanner.config import ScannerConfig, load_config
from scanner.db import PolilyDB
from scanner.filters import FilterResult, apply_hard_filters
from scanner.mispricing import MispricingResult, detect_mispricing
from scanner.models import BookLevel, Market
from scanner.paper_trading import PaperTradingDB
from scanner.pipeline import run_scan_pipeline
from scanner.reporting import ScoredCandidate, TierResult
from scanner.scoring import ScoreBreakdown, compute_structure_score
from scanner.tag_classifier import classify_from_tags

__all__ = [
    # Core types
    "Market", "BookLevel", "ScannerConfig", "load_config", "PolilyDB",
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
    # Paper trading
    "PaperTradingDB",
]
