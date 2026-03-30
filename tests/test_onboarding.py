"""Tests for first-run onboarding."""

import tempfile
from pathlib import Path

from scanner.onboarding import WELCOME_TEXT, mark_onboarding_done, should_show_onboarding


class TestOnboarding:
    def test_should_show_when_marker_missing(self):
        with tempfile.TemporaryDirectory() as d:
            assert should_show_onboarding(Path(d) / ".onboarding_done") is True

    def test_should_not_show_when_marker_exists(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".onboarding_done"
            marker.touch()
            assert should_show_onboarding(marker) is False

    def test_mark_done_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".onboarding_done"
            mark_onboarding_done(marker)
            assert marker.exists()

    def test_mark_done_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "sub" / "dir" / ".onboarding_done"
            mark_onboarding_done(marker)
            assert marker.exists()

    def test_welcome_text_contains_key_info(self):
        assert "polily scan" in WELCOME_TEXT
        assert "paper" in WELCOME_TEXT.lower()
