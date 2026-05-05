"""v0.11.5: live commentary rendering tracks current UI language.

Pre-v0.11.5, score commentary was persisted in score_breakdown JSON.
F2 toggle updated UI labels but commentary stayed in whatever language
the daemon last scored in — visibly stale (user reported this in dev
testing 2026-05-05).

The fix: view layer calls `render_commentary(...)` which reads
`polily.tui.i18n.current_language()` on every render. These tests
verify the same `breakdown` dict produces zh and en output when the
language is toggled.
"""
from __future__ import annotations


def _sample_breakdown():
    return {
        "liquidity": 30,
        "verifiability": 25,
        "probability": 20,
        "time": 15,
        "friction": 10,
    }


def test_render_commentary_returns_zh_when_language_zh():
    from polily.tui.commentary_render import render_commentary
    from polily.tui.i18n import set_language

    set_language("zh")
    try:
        result = render_commentary(
            _sample_breakdown(),
            total_score=50.0,
            market_id="test_market_id_aaa",
            market_type="other",
        )
    finally:
        set_language("zh")

    # zh joiner
    assert "。" in result["overall"], (
        f"zh commentary should use Chinese full-width period, got: {result['overall']!r}"
    )


def test_render_commentary_returns_en_after_language_switch():
    """Same call after `set_language('en')` returns English commentary
    — proves no caching of the old language's output.
    """
    from polily.tui.commentary_render import render_commentary
    from polily.tui.i18n import set_language

    breakdown = _sample_breakdown()
    args = {
        "total_score": 50.0,
        "market_id": "test_market_id_bbb",
        "market_type": "other",
    }

    set_language("zh")
    try:
        zh_result = render_commentary(breakdown, **args)
        set_language("en")
        en_result = render_commentary(breakdown, **args)
    finally:
        set_language("zh")

    # zh has 。 joiner; en uses ". " (period+space)
    assert "。" in zh_result["overall"]
    assert "。" not in en_result["overall"], (
        f"en commentary must not contain Chinese punctuation; "
        f"got: {en_result['overall']!r}"
    )
    # en commentary must contain ASCII letters (i.e. real English text)
    assert any(c.isascii() and c.isalpha() for c in en_result["overall"])
    # The two language outputs should differ
    assert zh_result["overall"] != en_result["overall"]


def test_render_commentary_no_caching_across_toggles():
    """F2 toggle simulation: zh → en → zh — third call returns the
    same zh content as first call. Proves the helper doesn't cache.
    """
    from polily.tui.commentary_render import render_commentary
    from polily.tui.i18n import set_language

    breakdown = _sample_breakdown()
    args = {
        "total_score": 60.0,
        "market_id": "test_market_id_ccc",
        "market_type": "other",
    }

    set_language("zh")
    try:
        first_zh = render_commentary(breakdown, **args)
        set_language("en")
        en = render_commentary(breakdown, **args)
        set_language("zh")
        second_zh = render_commentary(breakdown, **args)
    finally:
        set_language("zh")

    assert first_zh["overall"] == second_zh["overall"], (
        "Toggling zh→en→zh must return identical zh output. "
        "Helper should not cache by market_id without language key."
    )
    assert first_zh["overall"] != en["overall"]


def test_pipeline_progress_step_renders_live_per_language():
    """v0.11.5: scan_log step rendering reads `name_key` / `detail_key`
    via `t()` at paint time, so F2 toggle re-translates persisted
    records on next render. Pre-v0.11.5 the rendered strings were
    baked in at emit time.

    Constructs a StepInfo + ScanStepRecord with i18n keys and verifies
    `_resolve_step_name` / `_resolve_step_detail` translate per
    `current_language()`.
    """
    from polily.tui.i18n import set_language
    from polily.tui.views.scan_log import (
        StepInfo,
        _resolve_step_detail,
        _resolve_step_name,
    )

    step = StepInfo(
        name="",
        name_key="pipeline.step.fetch_event",
        status="done",
        detail_key="pipeline.detail.event_summary",
        detail_params={"title": "Test Event", "count": 6},
    )

    set_language("zh")
    try:
        zh_name = _resolve_step_name(step)
        zh_detail = _resolve_step_detail(step)
        set_language("en")
        en_name = _resolve_step_name(step)
        en_detail = _resolve_step_detail(step)
    finally:
        set_language("zh")

    assert zh_name == "获取事件"
    assert en_name == "Fetch event"
    assert zh_name != en_name
    # Detail with params: zh and en differ but both contain the title
    assert "Test Event" in zh_detail
    assert "Test Event" in en_detail
    assert zh_detail != en_detail
    assert "市场" in zh_detail
    assert "markets" in en_detail


def test_pipeline_progress_step_legacy_name_reverse_translates():
    """Pre-v0.11.5 persisted records have only `name` / `detail`
    (literal strings, no keys). Renderer reverse-matches the literal
    against known catalog entries so F2 flips legacy rows too.
    """
    from polily.tui.i18n import set_language
    from polily.tui.views.scan_log import StepInfo, _resolve_step_name

    legacy = StepInfo(
        name="获取事件",  # zh literal persisted by pre-v0.11.5 pipeline
        name_key=None,
        status="done",
        detail="",
        detail_key=None,
        detail_params=None,
    )

    set_language("zh")
    try:
        assert _resolve_step_name(legacy) == "获取事件"
        set_language("en")
        # F2 → legacy zh literal flips to en via reverse-lookup
        assert _resolve_step_name(legacy) == "Fetch event"
    finally:
        set_language("zh")


def test_pipeline_progress_step_legacy_detail_reverse_translates():
    """Legacy detail strings ('US x Iran ... (6 市场)', '事件 72 分')
    reverse-match against template patterns and re-translate with
    extracted params so F2 flips them.
    """
    from polily.tui.i18n import set_language
    from polily.tui.views.scan_log import StepInfo, _resolve_step_detail

    cases = [
        # event_summary
        StepInfo(
            name="", status="done",
            detail="US x Iran permanent peace deal? (6 市场)",
        ),
        # market_count
        StepInfo(name="", status="done", detail="6 市场"),
        # event_score
        StepInfo(name="", status="done", detail="事件 72 分"),
    ]

    set_language("zh")
    try:
        # In zh mode, legacy zh strings render unchanged
        assert "市场" in _resolve_step_detail(cases[0])
        assert "市场" in _resolve_step_detail(cases[1])
        assert "分" in _resolve_step_detail(cases[2])

        # F2 → en — pattern match recovers params, t() renders en
        set_language("en")
        en_summary = _resolve_step_detail(cases[0])
        en_market_count = _resolve_step_detail(cases[1])
        en_score = _resolve_step_detail(cases[2])
    finally:
        set_language("zh")

    assert "markets" in en_summary
    assert "US x Iran" in en_summary  # title preserved
    assert "(6 markets)" in en_summary
    assert en_market_count == "6 markets"
    assert "Event" in en_score
    assert "72" in en_score
    assert "pts" in en_score


def test_pipeline_progress_step_unknown_legacy_strings_pass_through():
    """If a legacy literal doesn't match any known template / name,
    the renderer leaves it as-is rather than crashing or hiding it.
    """
    from polily.tui.views.scan_log import (
        StepInfo,
        _resolve_step_detail,
        _resolve_step_name,
    )

    unknown = StepInfo(
        name="some custom step name",
        name_key=None,
        status="done",
        detail="something the regex doesn't match",
        detail_key=None,
        detail_params=None,
    )

    assert _resolve_step_name(unknown) == "some custom step name"
    assert _resolve_step_detail(unknown) == "something the regex doesn't match"


def test_pipeline_does_not_persist_commentary_string():
    """Regression source-level: pipeline.py and score_refresh.py must not
    write `bd["commentary"]` (or equivalent) into the persisted JSON.

    Source-grep test rather than full integration — proves the writer
    sites are clean without the heavy fixture setup. If a future PR
    re-introduces persistence, this fails loudly with the offending file.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    pipeline_src = (repo_root / "polily/scan/pipeline.py").read_text(
        encoding="utf-8",
    )
    score_refresh_src = (repo_root / "polily/daemon/score_refresh.py").read_text(
        encoding="utf-8",
    )

    # Forbidden patterns — assigning a `commentary` key into a breakdown
    # dict that gets json.dumps'd to db.
    forbidden = ('bd["commentary"]', "new_bd[\"commentary\"]")

    for src_name, src in (
        ("polily/scan/pipeline.py", pipeline_src),
        ("polily/daemon/score_refresh.py", score_refresh_src),
    ):
        for pat in forbidden:
            # Allow comments / docstrings to mention the pattern (those
            # are fine, e.g., "v0.11.5: bd no longer includes commentary")
            for lineno, line in enumerate(src.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                if pat in line and "=" in line and "pop" not in line:
                    raise AssertionError(
                        f"v0.11.5 invariant violation: "
                        f"{src_name}:{lineno} writes {pat!r} — view layer "
                        f"renders commentary live, no need to persist.\n"
                        f"  Offending line: {line.strip()!r}"
                    )
