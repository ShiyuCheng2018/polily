"""Polily — Polymarket research assistant.

Public API for programmatic use (without CLI).
"""

__version__ = "0.1.0"

from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.models import BookLevel, Market
from scanner.paper_trading import PaperTradingDB
from scanner.scan.filters import FilterResult, apply_hard_filters
from scanner.scan.mispricing import MispricingResult, detect_mispricing
from scanner.scan.pipeline import run_scan_pipeline
from scanner.scan.reporting import ScoredCandidate, TierResult
from scanner.scan.scoring import ScoreBreakdown, compute_structure_score
from scanner.scan.tag_classifier import classify_from_tags

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
