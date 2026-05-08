"""v0.12.0 wheel packaging — manual.md / protocol.md / default.md must ship.

Verifies the ``[tool.hatch.build.targets.wheel.force-include]`` table
covers every non-Python content file the runtime needs. Also pins the
``polily-geek`` default theme switch (was ``polily-dark`` pre-v0.12.0).
"""
import inspect
from pathlib import Path

import polily


def test_manual_md_is_in_package():
    p = Path(polily.__file__).parent / "agents" / "manual.md"
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    # Generator-produced content has the canonical first heading from 01_persona.md
    assert "## 1. Who You Are" in content


def test_protocol_md_is_in_package():
    p = Path(polily.__file__).parent / "agents" / "protocol.md"
    assert p.exists()
    assert "Output Protocol" in p.read_text(encoding="utf-8")


def test_default_strategy_is_in_package():
    p = Path(polily.__file__).parent / "strategies" / "default.md"
    assert p.exists()
    assert "Polily Default Analysis Strategy" in p.read_text(encoding="utf-8")


def test_skill_sources_core_files_are_in_package():
    """Generator regenerates manual.md from these — must ship in wheel."""
    base = Path(polily.__file__).parent / "agents" / "skill_sources" / "core"
    expected = [
        "01_persona.md",
        "02_mechanics.md",
        "03_db_schema.md",
        "04_data_freshness.md",
        "05_file_paths.md",
        "06_operational_lines.md",
        "07_per_call_ephemeral.md",
    ]
    for name in expected:
        assert (base / name).exists(), f"Missing skill source: {name}"


def test_register_polily_theme_sets_geek_as_default():
    """v0.12.0 default theme is polily-geek (was polily-dark in v0.11.x)."""
    from polily.tui import theme as theme_module
    src = inspect.getsource(theme_module.register_polily_theme)
    assert 'app.theme = "polily-geek"' in src, (
        "register_polily_theme must set polily-geek as default in v0.12.0"
    )
    assert 'app.theme = "polily-dark"' not in src, (
        "polily-dark default was removed in v0.12.0"
    )
