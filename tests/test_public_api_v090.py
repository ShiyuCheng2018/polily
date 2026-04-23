"""Post-rename smoke: every name listed in polily/__init__.py __all__
must import cleanly from the top-level `polily` package. Catches missed
exports / stale imports that pytest suites using nested paths wouldn't
notice."""


def test_public_api_symbols_importable():
    from polily import (
        BookLevel,
        EventRow,
        Market,
        MarketRow,
        MispricingResult,
        PolilyConfig,
        PolilyDB,
        ScoreBreakdown,
        ScoredCandidate,
        compute_structure_score,
        detect_mispricing,
        fetch_and_score_event,
        load_config,
    )
    # Existence + callability of the few functions in the list
    assert callable(load_config)
    assert callable(fetch_and_score_event)
    assert callable(compute_structure_score)
    assert callable(detect_mispricing)
