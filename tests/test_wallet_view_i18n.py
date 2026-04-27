"""Wallet view i18n smoke test — labels flip when language changes."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import Static

from polily.core.db import PolilyDB
from polily.core.events import TOPIC_LANGUAGE_CHANGED
from polily.tui import i18n
from polily.tui.service import PolilyService


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.tui.heartbeat_seconds = 5.0
    cfg.tui.language = "zh"
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    s = PolilyService(config=cfg, db=db)
    yield s
    db.close()


def _all_static_text(view) -> str:
    parts = []
    for s in view.query(Static):
        val = getattr(s, "renderable", None) or getattr(s, "content", None)
        if val is not None:
            parts.append(str(val))
    return " ".join(parts)


@pytest.mark.asyncio
async def test_wallet_static_labels_flip_on_language_change(svc):
    """KVRow labels and titles must change after TOPIC_LANGUAGE_CHANGED is emitted."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.wallet import WalletView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()

        zh_text = _all_static_text(view)
        # Spot-check zh starting state
        assert "余额概览" in zh_text
        assert "交易流水" in zh_text
        assert "浮动盈亏" in zh_text

        # Switch language and let the bus fire.
        await app.action_toggle_language()
        await pilot.pause()

        en_text = _all_static_text(view)
        # Static labels must have flipped to English.
        assert "Balance Overview" in en_text, en_text[:500]
        assert "Transactions" in en_text, en_text[:500]
        assert "Unrealized P&L" in en_text, en_text[:500]
        # And the zh strings should be gone.
        assert "余额概览" not in en_text
        assert "交易流水" not in en_text


@pytest.mark.asyncio
async def test_wallet_view_unsubscribes_lang_topic_on_unmount(svc):
    """Regression: unmount must not leak the lang-changed handler — otherwise
    handlers from many WalletView instances accumulate across re-mounts."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.wallet import WalletView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        # Snapshot subscriber count for our topic.
        before = len(svc.event_bus._subs.get(TOPIC_LANGUAGE_CHANGED, []))
        await view.remove()
        await pilot.pause()
        after = len(svc.event_bus._subs.get(TOPIC_LANGUAGE_CHANGED, []))
        assert after == before - 1, f"handler leak: {before} → {after}"
