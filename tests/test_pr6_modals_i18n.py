"""i18n smoke tests for PR-6 modal migrations.

Modals are short-lived screens; we don't push them through `app.run_test()`
just to assert text — that path is covered by per-modal v080 tests. Here
we focus on i18n glue: confirm key resolution + confirm the catalog has
all the keys these modals reference."""
from __future__ import annotations

import pytest

from polily.tui import i18n


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def test_modal_keys_resolve_in_zh_and_en():
    """Spot-check a sample of modal-relevant keys; full key-set parity is
    enforced by test_bundled_catalogs_have_consistent_key_sets."""
    sample = [
        ("topup.title", "充值", "Top-up"),
        ("withdraw.title", "提现", "Withdraw"),
        ("trade.title", "交易", "Trade"),
        ("trade.tab.buy", "买入", "Buy"),
        ("trade.tab.sell", "卖出", "Sell"),
        ("scan_modal.title.cancel", "取消分析", "Cancel Analysis"),
        ("monitor_modal.title", "确认取消监控", "Confirm Stop Monitor"),
        ("reset.confirm_button", "重置", "Reset"),
    ]
    for key, zh, _en in sample:
        assert i18n.t(key) == zh, f"zh mismatch for {key}"
    i18n.set_language("en")
    for key, _zh, en in sample:
        assert i18n.t(key) == en, f"en mismatch for {key}"


def test_format_templates_accept_kwargs():
    # Sanity-check that the few format templates used by modals accept the
    # documented kwargs without KeyError. Catches argument-name typos in
    # catalog drift.
    i18n.set_language("zh")
    assert "+$5.00" in i18n.t("topup.success", amt=5.0)
    assert "-$3.00" in i18n.t("withdraw.success", amt=3.0)
    assert "10s" in i18n.t("scan_modal.elapsed", elapsed=10.0)
    assert "PID 42" in i18n.t("reset.warn.daemon_running", pid=42)

    i18n.set_language("en")
    assert "+$5.00" in i18n.t("topup.success", amt=5.0)
    # Smoke: format template accepts the expected kwargs without raising.
    sell_label = i18n.t("trade.button.sell_with_price", side="YES", price=42.0)
    assert "YES" in sell_label and "42.0¢" in sell_label
