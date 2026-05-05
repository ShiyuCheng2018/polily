"""Market scoring commentary — phrase selection + cross-product overall.

v0.11.5: bilingual support. `phrases.{lang}.yaml` files live under
`polily.config`; `_load_phrases(language)` picks the right one. Falls
back to zh on unknown languages. Caller passes `language` explicitly
(via the `generate_commentary(..., language=...)` param) — keeps
`scan/` framework-free of `tui/i18n/` direct coupling.
"""

import hashlib
from importlib.resources import files

import yaml

# Per-language cache: {"zh": dict, "en": dict}
_PHRASES_CACHE: dict[str, dict] = {}

_FALLBACK_LANG = "zh"

# v0.11.2 + v0.11.5: phrases live under `polily.config` subpackage so
# `importlib.resources.files()` resolves identically across editable +
# pip + pipx install methods. Returns a Traversable (NOT pathlib.Path);
# always use Traversable-supported APIs (.is_file, .read_text, .open).


def _phrases_path(language: str):
    """Return the Traversable for `phrases.<lang>.yaml`, fallback to zh."""
    candidate = files("polily.config") / f"phrases.{language}.yaml"
    if candidate.is_file():
        return candidate
    return files("polily.config") / f"phrases.{_FALLBACK_LANG}.yaml"


def _load_phrases(language: str = _FALLBACK_LANG) -> dict:
    """Load (and cache) phrases for the given language. Falls back to zh
    if the requested language file is missing.
    """
    if language not in _PHRASES_CACHE:
        path = _phrases_path(language)
        _PHRASES_CACHE[language] = yaml.safe_load(
            path.read_text(encoding="utf-8"),
        )
    return _PHRASES_CACHE[language]


def _normalize_pct(weighted_score: float, max_weight: float) -> float:
    if max_weight <= 0:
        return 0.0
    return min(100.0, max(0.0, (weighted_score / max_weight) * 100))


def _level_index(pct: float) -> int:
    return min(19, int(pct / 5))


def _pick_variant(market_id: str, dimension: str, num_variants: int = 3) -> int:
    digest = hashlib.md5(f"{market_id}:{dimension}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % num_variants


def get_dimension_phrase(
    dimension: str,
    weighted_score: float,
    max_weight: float,
    market_id: str,
    language: str = _FALLBACK_LANG,
) -> str:
    phrases = _load_phrases(language)
    pct = _normalize_pct(weighted_score, max_weight)
    idx = _level_index(pct)
    dim_data = phrases["dimensions"][dimension]
    level_phrases = dim_data["levels"][idx]["phrases"]
    variant = _pick_variant(market_id, dimension, len(level_phrases))
    return level_phrases[variant]


def generate_commentary(
    breakdown: dict,
    total_score: float,
    market_id: str,
    market_type: str = "other",
    language: str = _FALLBACK_LANG,
) -> dict:
    """Generate full commentary from score breakdown.

    Args:
        breakdown: dict with keys like liquidity, verifiability, etc. (weighted scores)
        total_score: total structure score (0-100)
        market_id: for deterministic phrase selection
        market_type: "crypto", "sports", "political", "other"
        language: "zh" or "en" — picks `phrases.<lang>.yaml`. v0.11.5
            addition; defaults to zh for backward compatibility. Callers
            should read `polily.core.user_prefs.get_pref(db, "language",
            "zh")` and pass through.

    Returns dict with:
        - dim_comments: {dimension: phrase} for each dimension
        - overall: full cross-product commentary string
        - judgment: overall judgment phrase
        - strongest_text: strongest dimension comment
        - weakest_text: weakest dimension comment
        - advice: actionable advice
    """
    from polily.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS

    phrases = _load_phrases(language)
    tw = _TYPE_WEIGHTS.get(market_type, _DEFAULT_WEIGHTS)

    # Generate per-dimension phrases
    dim_comments = {}
    dim_pcts = {}
    dims = ["liquidity", "verifiability", "probability", "time", "friction"]
    if tw.get("net_edge", 0) > 0:
        dims.append("net_edge")

    for dim in dims:
        score = breakdown.get(dim, 0)
        max_w = tw.get(dim, 0)
        if max_w <= 0:
            continue
        pct = _normalize_pct(score, max_w)
        dim_pcts[dim] = pct
        dim_comments[dim] = get_dimension_phrase(dim, score, max_w, market_id, language=language)

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

    # Joiner: zh uses \u3002 (full-width period); en uses ". " (period + space).
    # Picked by language so the rendered overall reads natural in either UI.
    joiner = "\u3002" if language == "zh" else ". "

    return {
        "dim_comments": dim_comments,
        "overall": joiner.join(parts),
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
