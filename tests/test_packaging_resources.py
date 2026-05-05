"""Catches packaging-bug regressions where code-asset files declared
inline (e.g. phrases.{zh,en}.yaml) are not actually shipped in the wheel.

v0.11.1 shipped with `polily/scan/commentary.py:9` resolving phrases.yaml
via `Path(__file__).resolve().parent.parent.parent / "config" / "phrases.yaml"`,
which silently worked under editable install (path resolves to repo root)
but blew up under pipx install (path resolves to site-packages, where no
top-level "config" dir exists).

v0.11.2 migrated phrases.yaml into the polily.config subpackage and uses
`importlib.resources` for path-resolution-method-agnostic access.

v0.11.5 split phrases into bilingual `phrases.zh.yaml` + `phrases.en.yaml`
for runtime i18n. The same packaging-resources pattern applies to both.

These tests exercise the SAME path-resolution pattern that runtime uses,
so they catch any future similar regressions before ship.
"""
from __future__ import annotations

import pytest

LANGS = ("zh", "en")


@pytest.mark.parametrize("language", LANGS)
def test_phrases_yaml_path_resolves(language):
    """Each `phrases.<lang>.yaml` must resolve to a real file via the
    same loader path that runtime uses.

    Catches:
    - Missing wheel inclusion (path doesn't exist)
    - Wrong path computation (e.g. parent.parent.parent on installed wheel)
    - Renamed file without code update

    Runs identically under editable install and pip/pipx install.
    """
    from polily.scan.commentary import _phrases_path

    path = _phrases_path(language)
    assert path.is_file(), (
        f"phrases.{language}.yaml not found at {path}. "
        f"Either the wheel didn't ship config/phrases.{language}.yaml as a "
        f"polily.config subpackage resource, or commentary.py's "
        f"path-resolution code is broken."
    )


@pytest.mark.parametrize("language", LANGS)
def test_phrases_yaml_content_loads_without_error(language):
    """Round-trip: actually read + parse each file (catches format breakage)."""
    import yaml

    from polily.scan.commentary import _phrases_path

    content = _phrases_path(language).read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), f"phrases.{language}.yaml must parse to a dict, got {type(data)}"
    assert len(data) > 0, f"phrases.{language}.yaml is empty — would render zero commentary"


@pytest.mark.parametrize("language", LANGS)
def test_phrases_yaml_resolvable_via_importlib_resources(language):
    """After v0.11.2 migration, phrases.<lang>.yaml MUST be a polily.config resource.

    importlib.resources.files works identically across editable and wheel
    installs — if this passes, prod ship is safe.
    """
    from importlib.resources import files

    yaml_path = files("polily.config") / f"phrases.{language}.yaml"
    assert yaml_path.is_file(), (
        f"phrases.{language}.yaml not found at {yaml_path}. "
        f"Run pyproject.toml force-include for polily/config/phrases.{language}.yaml."
    )


@pytest.mark.parametrize("language", LANGS)
def test_load_phrases_round_trip(language):
    """End-to-end: invoke _load_phrases(language) to verify Traversable-friendly
    file access (read_text, not builtin open).

    Catches regressions where someone reverts to `with open(...)` —
    would silently work on filesystem-backed installs but break on
    edge cases the unit tests don't cover.
    """
    from polily.scan.commentary import _load_phrases

    data = _load_phrases(language)
    assert isinstance(data, dict)
    assert "dimensions" in data, (
        f"phrases.{language}.yaml must have 'dimensions' top-level key — "
        f"renderer at commentary.get_dimension_phrase relies on it. "
        f"Got top-level keys: {list(data.keys())}"
    )


# ---------------------------------------------------------------------------
# v0.11.5 parity: zh and en catalogs MUST have the same structure.
# Mirrors Yuan's tests/test_i18n.py::test_bundled_catalogs_have_consistent_key_sets
# but for the commentary phrase catalogs.
# ---------------------------------------------------------------------------


def test_phrases_yaml_zh_and_en_have_same_dimensions():
    """Both languages must declare the same set of dimension keys.

    A new dimension added in zh but not en (or vice versa) would crash
    `get_dimension_phrase` for the missing language with KeyError.
    """
    from polily.scan.commentary import _load_phrases

    zh = _load_phrases("zh")
    en = _load_phrases("en")

    zh_dims = set(zh["dimensions"].keys())
    en_dims = set(en["dimensions"].keys())

    missing_in_en = zh_dims - en_dims
    missing_in_zh = en_dims - zh_dims

    assert not missing_in_en and not missing_in_zh, (
        f"Dimension key set mismatch between phrases.zh.yaml and "
        f"phrases.en.yaml.\n"
        f"  Missing in en: {sorted(missing_in_en)}\n"
        f"  Missing in zh: {sorted(missing_in_zh)}"
    )


def test_phrases_yaml_zh_and_en_have_same_level_count_per_dimension():
    """Each dimension must have the same number of levels in both
    languages (level index calculation is shared between zh + en).
    """
    from polily.scan.commentary import _load_phrases

    zh = _load_phrases("zh")
    en = _load_phrases("en")

    for dim in zh["dimensions"]:
        zh_levels = len(zh["dimensions"][dim]["levels"])
        en_levels = len(en["dimensions"][dim]["levels"])
        assert zh_levels == en_levels, (
            f"Dimension {dim!r}: zh has {zh_levels} levels, "
            f"en has {en_levels}. Counts must match — _level_index() "
            f"returns the same int for either language."
        )


def test_phrases_yaml_zh_and_en_overall_structure_matches():
    """`overall.total_judgment` ranges + `overall.advice` condition keys
    must match across languages so condition matching is deterministic."""
    from polily.scan.commentary import _load_phrases

    zh = _load_phrases("zh")
    en = _load_phrases("en")

    # total_judgment: same range count
    zh_judgment_count = len(zh["overall"]["total_judgment"])
    en_judgment_count = len(en["overall"]["total_judgment"])
    assert zh_judgment_count == en_judgment_count, (
        f"overall.total_judgment count mismatch: zh={zh_judgment_count}, "
        f"en={en_judgment_count}"
    )

    # strongest / weakest templates: same count
    assert len(zh["overall"]["strongest"]) == len(en["overall"]["strongest"])
    assert len(zh["overall"]["weakest"]) == len(en["overall"]["weakest"])

    # advice: same count + same condition keys
    zh_advice = zh["overall"]["advice"]
    en_advice = en["overall"]["advice"]
    assert len(zh_advice) == len(en_advice), (
        f"overall.advice count mismatch: zh={len(zh_advice)}, "
        f"en={len(en_advice)}"
    )
    for i, (zh_rule, en_rule) in enumerate(zip(zh_advice, en_advice, strict=True)):
        zh_cond = zh_rule["condition"]
        en_cond = en_rule["condition"]
        assert zh_cond == en_cond, (
            f"overall.advice[{i}] condition mismatch:\n"
            f"  zh: {zh_cond}\n"
            f"  en: {en_cond}"
        )


def test_phrases_yaml_unknown_language_falls_back_to_zh():
    """Loading an unsupported language gracefully falls back to zh
    rather than raising — protects against future code paths that
    pass a typo'd or new language string.
    """
    from polily.scan.commentary import _load_phrases

    zh = _load_phrases("zh")
    fallback = _load_phrases("nonexistent-lang-code")

    # Same content, since unknown lang resolves to the zh file
    assert fallback["dimensions"].keys() == zh["dimensions"].keys()


def test_generate_commentary_returns_english_when_language_en():
    """End-to-end: pass language='en' and verify the returned phrases
    look English (heuristic: contains ASCII letters in dimension comments).
    """
    from polily.scan.commentary import generate_commentary

    breakdown = {
        "liquidity": 30,
        "verifiability": 30,
        "probability": 30,
        "time": 30,
        "friction": 30,
    }
    result = generate_commentary(
        breakdown, total_score=60.0, market_id="test_market_en",
        market_type="other", language="en",
    )

    # Joiner for en is ". " (period + space), not "。" (zh full-width)
    assert "。" not in result["overall"], (
        f"English commentary should not contain Chinese full-width "
        f"period; got: {result['overall']!r}"
    )
    # judgment should have ASCII content
    assert any(c.isascii() and c.isalpha() for c in result["judgment"]), (
        f"English judgment should contain ASCII letters; "
        f"got: {result['judgment']!r}"
    )
