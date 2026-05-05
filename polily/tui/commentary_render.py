"""v0.11.5: live commentary rendering — F2 language toggle takes effect immediately.

Pre-v0.11.5, score commentary text was persisted in `markets.score_breakdown`
JSON (under `commentary.overall` and `commentary.dim_comments`). The
language was baked in at scoring time, so F2-toggling the UI updated
labels and tooltips live but left commentary stuck in the prior
language — visibly inconsistent.

This module re-generates commentary on every render via
`generate_commentary(..., language=current_language())`. Combined with
v0.11.5 dropping the persisted commentary write in `pipeline.py` and
`score_refresh.py`, F2 toggle now refreshes commentary instantly,
mirroring how the rest of the i18n stack works.

Cheap: phrase yaml caches per-language inside `polily.scan.commentary`;
selection is dict lookups + a single md5 of `market_id`.
"""
from __future__ import annotations

from typing import Any

from polily.scan.commentary import generate_commentary
from polily.tui.i18n import current_language


def render_commentary(
    breakdown: dict[str, Any],
    total_score: float,
    market_id: str,
    market_type: str = "other",
) -> dict:
    """Generate commentary in the user's current UI language.

    Args:
        breakdown: parsed `markets.score_breakdown` JSON dict. Must
            contain weighted dimension scores under the canonical keys
            (`liquidity`, `verifiability`, `probability`, `time`,
            `friction`; `net_edge` for crypto markets).
        total_score: `markets.structure_score` (0-100).
        market_id: deterministic phrase variant seed (md5 of
            `f"{market_id}:{dimension}"` mod num_variants).
        market_type: `"crypto"` / `"crypto_threshold"` / `"sports"` /
            `"political"` / `"other"`. Drives weight selection.

    Returns same shape as `polily.scan.commentary.generate_commentary`:
        {dim_comments, overall, judgment, strongest_text, weakest_text, advice}
    """
    return generate_commentary(
        breakdown,
        total_score,
        market_id,
        market_type=market_type,
        language=current_language(),
    )
