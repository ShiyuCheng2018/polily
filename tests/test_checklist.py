"""Tests for research checklist loading."""

from scanner.checklist import load_checklist


class TestLoadChecklist:
    def test_load_crypto_threshold(self):
        steps = load_checklist("crypto_threshold")
        assert len(steps) >= 5
        assert any("resolution" in s.lower() for s in steps)

    def test_load_economic_data(self):
        steps = load_checklist("economic_data")
        assert any("instant" in s.lower() or "no exit" in s.lower() for s in steps)

    def test_load_political(self):
        steps = load_checklist("political")
        assert any("poll" in s.lower() for s in steps)

    def test_unknown_type_falls_back_to_default(self):
        steps = load_checklist("unknown_type_xyz")
        assert len(steps) >= 3

    def test_default_checklist(self):
        steps = load_checklist("default")
        assert any("resolution" in s.lower() for s in steps)
