"""PR-7 cleanup smoke tests: sidebar + countdown + status bar."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from polily.tui import i18n
from polily.tui.utils import _relative


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def test_countdown_relative_translates():
    """`_relative` formats relative time using countdown.* catalog keys."""
    future_3d = (datetime.now(UTC) + timedelta(days=3, hours=2)).isoformat()
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    assert "天" in _relative(future_3d)
    assert _relative(past) == "已过期"

    i18n.set_language("en")
    out = _relative(future_3d)
    assert "d" in out and "h" in out
    assert _relative(past) == "Expired"


def test_sidebar_keys_resolve():
    sample = [
        ("sidebar.tasks", "任务记录", "Tasks"),
        ("sidebar.monitor", "监控列表", "Monitor"),
        ("sidebar.paper", "持仓", "Positions"),
        ("sidebar.wallet", "钱包", "Wallet"),
        ("sidebar.history", "历史", "History"),
        ("sidebar.archive", "归档", "Archive"),
        ("sidebar.changelog", "更新日志", "Changelog"),
    ]
    for key, zh, _en in sample:
        assert i18n.t(key) == zh, f"zh mismatch for {key}"
    i18n.set_language("en")
    for key, _zh, en in sample:
        assert i18n.t(key) == en, f"en mismatch for {key}"


def test_main_status_keys_resolve_with_format():
    assert "评分完成" in i18n.t("main.status.score_complete", title="Test", score=80)
    i18n.set_language("en")
    assert "Scored" in i18n.t("main.status.score_complete", title="Test", score=80)


def test_widget_buy_sell_verb_keys():
    assert i18n.t("widget.buy_sell.verb.buy") == "买"
    assert i18n.t("widget.buy_sell.verb.sell") == "卖"
    i18n.set_language("en")
    assert i18n.t("widget.buy_sell.verb.buy") == "Buy"
    assert i18n.t("widget.buy_sell.verb.sell") == "Sell"
