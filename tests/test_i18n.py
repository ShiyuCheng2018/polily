"""Tests for polily.tui.i18n — runtime translation lookup + language switching."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from polily.tui import i18n


@pytest.fixture(autouse=True)
def _reset_i18n_state():
    """Restore bundled catalogs after each test so other test files
    (which don't explicitly init) still see real translations."""
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def test_t_returns_key_when_uninitialized():
    # No init_i18n called yet → fallback to key string itself, never raises.
    i18n.init_i18n({}, default="zh")
    assert i18n.t("missing.key") == "missing.key"


def test_t_resolves_in_current_language():
    i18n.init_i18n(
        {"zh": {"binding.quit": "退出"}, "en": {"binding.quit": "Quit"}},
        default="zh",
    )
    assert i18n.t("binding.quit") == "退出"
    i18n.set_language("en")
    assert i18n.t("binding.quit") == "Quit"


def test_t_falls_back_to_zh_when_key_missing_in_current():
    i18n.init_i18n(
        {"zh": {"wallet.balance": "当前余额"}, "en": {}},
        default="en",
    )
    # current=en has no "wallet.balance" → fall back to zh
    assert i18n.t("wallet.balance") == "当前余额"


def test_t_returns_key_when_missing_in_all_languages():
    i18n.init_i18n({"zh": {}, "en": {}}, default="zh")
    assert i18n.t("nonexistent.key") == "nonexistent.key"


def test_t_supports_format_vars():
    i18n.init_i18n(
        {"zh": {"scan.analyzing": "正在分析... ({elapsed}s)"}},
        default="zh",
    )
    assert i18n.t("scan.analyzing", elapsed=12) == "正在分析... (12s)"


def test_set_language_to_unknown_raises():
    i18n.init_i18n({"zh": {}, "en": {}}, default="zh")
    with pytest.raises(ValueError, match="unknown language"):
        i18n.set_language("ja")


def test_current_language_reflects_init_default():
    i18n.init_i18n({"zh": {}, "en": {}}, default="en")
    assert i18n.current_language() == "en"


def test_available_languages_returns_loaded_codes():
    i18n.init_i18n({"zh": {}, "en": {}, "ja": {}}, default="zh")
    assert i18n.available_languages() == ["en", "ja", "zh"]


def test_translate_status_backward_compat():
    """Old translate_status() callers continue to work."""
    i18n.init_i18n({"zh": {"status.pending": "待执行"}}, default="zh")
    assert i18n.translate_status("pending") == "待执行"
    # Unknown status → returned as-is
    assert i18n.translate_status("frobnicated") == "frobnicated"


def test_translate_trigger_backward_compat():
    i18n.init_i18n({"zh": {"trigger.manual": "手动"}}, default="zh")
    assert i18n.translate_trigger("manual") == "手动"


# --- loader tests ---

def test_loader_scans_directory_for_json_files(tmp_path: Path):
    (tmp_path / "zh.json").write_text(json.dumps({"a": "甲"}), encoding="utf-8")
    (tmp_path / "en.json").write_text(json.dumps({"a": "A"}), encoding="utf-8")
    catalogs = i18n.load_catalogs(tmp_path)
    assert catalogs == {"zh": {"a": "甲"}, "en": {"a": "A"}}


def test_loader_ignores_non_json_files(tmp_path: Path):
    (tmp_path / "zh.json").write_text(json.dumps({"a": "甲"}), encoding="utf-8")
    (tmp_path / "README.md").write_text("not a catalog")
    catalogs = i18n.load_catalogs(tmp_path)
    assert catalogs == {"zh": {"a": "甲"}}


def test_loader_skips_malformed_json_with_warning(tmp_path: Path, caplog):
    (tmp_path / "zh.json").write_text(json.dumps({"a": "甲"}), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    catalogs = i18n.load_catalogs(tmp_path)
    # broken file is skipped, valid file still loads
    assert "zh" in catalogs
    assert "broken" not in catalogs


def test_loader_returns_empty_dict_for_empty_directory(tmp_path: Path):
    assert i18n.load_catalogs(tmp_path) == {}


def test_loader_returns_empty_dict_for_missing_directory(tmp_path: Path):
    # Pointing at a non-existent path should not raise
    assert i18n.load_catalogs(tmp_path / "does_not_exist") == {}


# --- key-set consistency (CI gate) ---

def test_bundled_catalogs_have_consistent_key_sets():
    """zh.json and en.json must define the same keys (CI gate for migrations)."""
    pkg_dir = Path(i18n.__file__).parent
    catalogs_dir = pkg_dir / "catalogs"
    catalogs = i18n.load_catalogs(catalogs_dir)
    if "zh" in catalogs and "en" in catalogs:
        zh_keys = set(catalogs["zh"].keys())
        en_keys = set(catalogs["en"].keys())
        missing_in_en = zh_keys - en_keys
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_en, f"keys in zh missing from en: {sorted(missing_in_en)}"
        assert not missing_in_zh, f"keys in en missing from zh: {sorted(missing_in_zh)}"
