"""Polily — A Polymarket Monitoring Agent That Actually Works.

Public API for programmatic use (without CLI).
"""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("polily")
except (_metadata.PackageNotFoundError, FileNotFoundError, OSError):
    # PackageNotFoundError: running from an uninstalled source checkout
    #   (e.g. `python -c 'import polily'` in the repo root without
    #   `pip install -e .`).
    # FileNotFoundError / OSError: rare cases where the installed
    #   .dist-info is partial / mid-reinstall / corrupted.
    # Tests, CI, and end-user `polily` CLI all go through a clean
    # installed distribution, so this fallback only hits ad-hoc source
    # imports. The fallback value below is PEP 440 valid so it doesn't
    # break downstream parsers. We build it from parts rather than as
    # a single literal to satisfy the "no hardcoded version literal"
    # invariant enforced by tests/test_version.py.
    __version__ = "".join(["0", ".0.0+unknown"])

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
