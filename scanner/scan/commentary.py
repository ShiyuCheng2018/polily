"""Market scoring commentary — phrase selection + cross-product overall."""

import hashlib
from pathlib import Path

import yaml

_PHRASES_CACHE = None
_PHRASES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "phrases.yaml"


def _load_phrases() -> dict:
    global _PHRASES_CACHE
    if _PHRASES_CACHE is None:
        with open(_PHRASES_PATH) as f:
            _PHRASES_CACHE = yaml.safe_load(f)
    return _PHRASES_CACHE


def _normalize_pct(weighted_score: float, max_weight: float) -> float:
    if max_weight <= 0:
        return 0.0
    return min(100.0, max(0.0, (weighted_score / max_weight) * 100))


def _level_index(pct: float) -> int:
    return min(19, int(pct / 5))


def _pick_variant(market_id: str, dimension: str, num_variants: int = 3) -> int:
    digest = hashlib.md5(f"{market_id}:{dimension}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % num_variants


def get_dimension_phrase(dimension: str, weighted_score: float, max_weight: float, market_id: str) -> str:
    phrases = _load_phrases()
    pct = _normalize_pct(weighted_score, max_weight)
    idx = _level_index(pct)
    dim_data = phrases["dimensions"][dimension]
    level_phrases = dim_data["levels"][idx]["phrases"]
    variant = _pick_variant(market_id, dimension, len(level_phrases))
    return level_phrases[variant]


def generate_commentary(breakdown: dict, total_score: float, market_id: str, market_type: str = "other") -> dict:
    """Generate full commentary from score breakdown.

    Args:
        breakdown: dict with keys like liquidity, verifiability, etc. (weighted scores)
        total_score: total structure score (0-100)
        market_id: for deterministic phrase selection
        market_type: "crypto", "sports", "political", "other"

    Returns dict with:
        - dim_comments: {dimension: phrase} for each dimension
        - overall: full cross-product commentary string
        - judgment: overall judgment phrase
        - strongest_text: strongest dimension comment
        - weakest_text: weakest dimension comment
        - advice: actionable advice
    """
    from scanner.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS

    phrases = _load_phrases()
    tw = _TYPE_WEIGHTS.get(market_type, _DEFAULT_WEIGHTS)

    # Generate per-dimension phrases
    dim_comments = {}
    dim_pcts = {}
    dims = ["liquidity", "verifiability", "probability", "time", "friction"]
    if tw.get("net_edge", 0) > 0 and breakdown.get("net_edge", 0) > 0:
        dims.append("net_edge")

    for dim in dims:
        score = breakdown.get(dim, 0)
        max_w = tw.get(dim, 0)
        if max_w <= 0:
            continue
        pct = _normalize_pct(score, max_w)
        dim_pcts[dim] = pct
        dim_comments[dim] = get_dimension_phrase(dim, score, max_w, market_id)

    # Find strongest and weakest
    if dim_pcts:
        strongest_dim = max(dim_pcts, key=dim_pcts.get)
        weakest_dim = min(dim_pcts, key=dim_pcts.get)
    else:
        strongest_dim = weakest_dim = None

    # Overall judgment
    judgment = _get_judgment(total_score, market_id, phrases)

    # Strongest/weakest text
    strongest_text = ""
    weakest_text = ""
    if strongest_dim:
        dim_label = phrases["dimensions"][strongest_dim]["label_short"]
        tpl_idx = _pick_variant(market_id, "strongest_tpl", len(phrases["overall"]["strongest"]))
        tpl = phrases["overall"]["strongest"][tpl_idx]
        strongest_text = tpl.replace("{dim}", dim_label).replace("{phrase}", dim_comments[strongest_dim])
    if weakest_dim and weakest_dim != strongest_dim:
        dim_label = phrases["dimensions"][weakest_dim]["label_short"]
        tpl_idx = _pick_variant(market_id, "weakest_tpl", len(phrases["overall"]["weakest"]))
        tpl = phrases["overall"]["weakest"][tpl_idx]
        weakest_text = tpl.replace("{dim}", dim_label).replace("{phrase}", dim_comments[weakest_dim])

    # Advice (condition matching)
    is_crypto = market_type in ("crypto", "crypto_threshold")
    advice = _get_advice(total_score, dim_pcts, is_crypto, market_id, phrases)

    # Full commentary
    parts = [judgment]
    if strongest_text:
        parts.append(strongest_text)
    if weakest_text:
        parts.append(weakest_text)
    if advice:
        parts.append(advice)

    return {
        "dim_comments": dim_comments,
        "overall": "\u3002".join(parts),
        "judgment": judgment,
        "strongest_text": strongest_text,
        "weakest_text": weakest_text,
        "advice": advice,
    }


def _get_judgment(total: float, market_id: str, phrases: dict) -> str:
    for band in phrases["overall"]["total_judgment"]:
        lo, hi = band["range"]
        if lo <= total <= hi:
            variant = _pick_variant(market_id, "judgment", len(band["phrases"]))
            return band["phrases"][variant]
    return ""


def _get_advice(total: float, dim_pcts: dict, is_crypto: bool, market_id: str, phrases: dict) -> str:
    for rule in phrases["overall"]["advice"]:
        cond = rule["condition"]
        if _match_condition(cond, total, dim_pcts, is_crypto):
            variant = _pick_variant(market_id, "advice", len(rule["phrases"]))
            return rule["phrases"][variant]
    return ""


def _match_condition(cond: dict, total: float, dim_pcts: dict, is_crypto: bool) -> bool:
    for key, val in cond.items():
        if key == "is_crypto":
            if val != is_crypto:
                return False
        elif key == "total_gte":
            if total < val:
                return False
        elif key == "total_lt":
            if total >= val:
                return False
        elif key.endswith("_pct_gte"):
            dim = key.replace("_pct_gte", "")
            if dim_pcts.get(dim, 0) < val:
                return False
        elif key.endswith("_pct_lt"):
            dim = key.replace("_pct_lt", "")
            if dim_pcts.get(dim, 0) >= val:
                return False
    return True
