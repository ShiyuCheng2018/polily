"""Tests for scripts/check_changelog.py — CHANGELOG release discipline validator."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load the script module from an explicit file path (cleaner than
# sys.path.insert — avoids global namespace pollution / collision risk).
# The module IS registered in sys.modules under a private name because
# Python 3.14's @dataclass decorator resolves type references via
# sys.modules[cls.__module__] during class creation; an unregistered
# module makes that lookup return None and @dataclass raises.
_MODULE_NAME = "_check_changelog_under_test"
_script_path = Path(__file__).parent.parent / "scripts" / "check_changelog.py"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _script_path)
check_changelog = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = check_changelog
_spec.loader.exec_module(check_changelog)


def _changelog_fixture(body: str) -> str:
    """Prepend the standard header so fixtures read like a real CHANGELOG.md."""
    header = (
        "# Changelog\n\n"
        "All notable changes to Polily are documented in this file.\n\n"
    )
    return header + body


# --- Happy path -----------------------------------------------------------


def test_valid_changelog_passes():
    """Top section is [0.9.3], footer has [0.9.3] link in tag format."""
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n"
        "- Something.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.3...dev\n"
        "[0.9.3]: https://github.com/x/y/releases/tag/v0.9.3\n"
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert result.ok, f"Expected ok=True, got errors: {result.errors}"


# --- Rejection paths ------------------------------------------------------


def test_rejects_unreleased_as_top_released_section():
    """If [Unreleased] is the ONLY section (no [X.Y.Z] below it), that means
    we're about to release without renaming — reject the release PR."""
    body = (
        "## [Unreleased]\n\n"
        "### Fixed\n\n"
        "- Something about to release.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.2...dev\n"
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    assert any("Unreleased" in e for e in result.errors)


def test_rejects_missing_footer_link():
    """Top versioned section has no matching footer link."""
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n"
        "- Something.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.3...dev\n"
        # missing [0.9.3] link
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    assert any("0.9.3" in e and "link" in e.lower() for e in result.errors)


def test_rejects_compare_format_for_released_version():
    """Historical version links must use releases/tag/ format, not compare/.

    Project convention per git history: every released version uses tag
    format from day one. `compare/vA...vB` format was a v0.9.0 footer mistake
    already fixed. CI enforces that we don't reintroduce it.
    """
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n- Something.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.3...dev\n"
        "[0.9.3]: https://github.com/x/y/compare/v0.9.2...v0.9.3\n"  # wrong
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    assert any("0.9.3" in e and "compare" in e.lower() for e in result.errors)


def test_rejects_stale_unreleased_link():
    """[Unreleased] footer link must compare against the top released version."""
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n- Something.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.0...dev\n"  # stale
        "[0.9.3]: https://github.com/x/y/releases/tag/v0.9.3\n"
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    assert any("Unreleased" in e and ("v0.9.3" in e or "stale" in e.lower())
               for e in result.errors)


def test_multiple_violations_accumulate_in_single_run():
    """When [Unreleased]-only CHANGELOG also has a stale/missing Unreleased
    link, BOTH errors surface in a single validate() call. Previously the
    script early-returned after Rule 1 and the user had to fix + rerun to
    discover Rule 4 was also broken."""
    body = (
        "## [Unreleased]\n\n"
        "### Fixed\n\n"
        "- Some feature.\n\n"
        # No footer links at all — Rule 4b should also fire
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    # Rule 1 fires (no released section)
    assert any("forgot to rename" in e for e in result.errors)
    # Rule 4b fires even with Rule 1 failure
    assert any("[Unreleased]" in e and "missing" in e.lower() for e in result.errors)
    # Should be 2 distinct errors
    assert len(result.errors) >= 2


def test_rejects_missing_unreleased_link():
    """[Unreleased] footer link is REQUIRED (per Keep-a-Changelog convention +
    project discipline). Missing-link is itself a violation, not something
    to silently pass."""
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n- Something.\n\n"
        # No [Unreleased]: ... footer link at all
        "[0.9.3]: https://github.com/x/y/releases/tag/v0.9.3\n"
    )
    result = check_changelog.validate(_changelog_fixture(body))
    assert not result.ok
    assert any("Unreleased" in e and "link" in e.lower() for e in result.errors)


# --- CLI entry ------------------------------------------------------------


def test_cli_entry_exits_zero_on_valid(tmp_path, capsys):
    """`python scripts/check_changelog.py <path>` exits 0 on success
    and emits a success line that mentions the path — pins the user-visible
    success contract so a silent-success regression is caught."""
    body = (
        "## [Unreleased]\n\n"
        "## [0.9.3] — 2026-04-24\n\n"
        "### Fixed\n\n- Something.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.3...dev\n"
        "[0.9.3]: https://github.com/x/y/releases/tag/v0.9.3\n"
    )
    p = tmp_path / "CHANGELOG.md"
    p.write_text(_changelog_fixture(body))
    exit_code = check_changelog.main([str(p)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert str(p) in captured.out


def test_cli_entry_exits_nonzero_on_invalid(tmp_path, capsys):
    body = (
        "## [Unreleased]\n\n"
        "### Fixed\n\n- About to release without rename.\n\n"
        "[Unreleased]: https://github.com/x/y/compare/v0.9.2...dev\n"
    )
    p = tmp_path / "CHANGELOG.md"
    p.write_text(_changelog_fixture(body))
    exit_code = check_changelog.main([str(p)])
    assert exit_code != 0
    captured = capsys.readouterr()
    # Errors printed to stdout or stderr — either acceptable, must mention Unreleased
    assert "Unreleased" in (captured.out + captured.err)
