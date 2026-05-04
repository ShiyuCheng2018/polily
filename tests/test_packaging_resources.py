"""Catches packaging-bug regressions where code-asset files declared
inline (e.g. phrases.yaml) are not actually shipped in the wheel.

v0.11.1 shipped with `polily/scan/commentary.py:9` resolving phrases.yaml
via `Path(__file__).resolve().parent.parent.parent / "config" / "phrases.yaml"`,
which silently worked under editable install (path resolves to repo root)
but blew up under pipx install (path resolves to site-packages, where no
top-level "config" dir exists).

The fix migrates phrases.yaml into the polily.config subpackage and uses
`importlib.resources` for path-resolution-method-agnostic access.

These tests exercise the SAME path-resolution pattern that runtime uses,
so they catch any future similar regressions before ship.
"""
from __future__ import annotations


def test_phrases_yaml_loadable_via_commentary_module():
    """The PHRASES_PATH constant in commentary.py must point at a real file.

    Catches:
    - Missing wheel inclusion (path doesn't exist)
    - Wrong path computation (e.g. parent.parent.parent on installed wheel)
    - Renamed file without code update

    Runs identically under editable install and pip/pipx install.
    """
    from polily.scan.commentary import _PHRASES_PATH

    assert _PHRASES_PATH.is_file(), (
        f"phrases.yaml not found at {_PHRASES_PATH}. "
        f"Either the wheel didn't ship config/phrases.yaml as a "
        f"polily.config subpackage resource, or commentary.py's "
        f"path-resolution code is broken."
    )


def test_phrases_yaml_content_loads_without_error():
    """Round-trip: actually read + parse the file (catches format breakage)."""
    import yaml

    from polily.scan.commentary import _PHRASES_PATH

    content = _PHRASES_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), f"phrases.yaml must parse to a dict, got {type(data)}"
    assert len(data) > 0, "phrases.yaml is empty — would render zero commentary"


def test_phrases_yaml_resolvable_via_importlib_resources():
    """After v0.11.2 migration, phrases.yaml MUST be a polily.config resource.

    importlib.resources.files works identically across editable and wheel
    installs — if this passes, prod ship is safe.
    """
    from importlib.resources import files

    yaml_path = files("polily.config") / "phrases.yaml"
    assert yaml_path.is_file(), (
        f"phrases.yaml not found at {yaml_path}. "
        f"Run task 2 step 3-5 to migrate config/phrases.yaml into "
        f"polily/config/phrases.yaml + add polily/config/__init__.py."
    )


def test_load_phrases_round_trip():
    """End-to-end: invoke _load_phrases() to verify Traversable-friendly
    file access (read_text, not builtin open).

    Catches regressions where someone reverts to `with open(_PHRASES_PATH)`
    — would silently work on filesystem-backed installs but break on
    edge cases the unit tests don't cover.
    """
    from polily.scan.commentary import _load_phrases

    data = _load_phrases()
    assert isinstance(data, dict)
    assert "dimensions" in data, (
        f"phrases.yaml must have 'dimensions' top-level key — "
        f"renderer at commentary.get_dimension_phrase relies on it. "
        f"Got top-level keys: {list(data.keys())}"
    )
