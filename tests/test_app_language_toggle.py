"""Test PolilyApp language toggle action — startup priority + cycle + persistence + bus."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.events import TOPIC_LANGUAGE_CHANGED
from polily.core.user_prefs import get_pref, set_pref
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


def test_init_uses_db_pref_over_config_default(svc):
    """If DB has user_prefs.language, that wins over config.tui.language."""
    set_pref(svc.db, "language", "en")
    from polily.tui.app import PolilyApp
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    assert i18n.current_language() == "en"


def test_init_falls_back_to_config_when_db_empty(svc):
    """No DB entry → use config.tui.language."""
    from polily.tui.app import PolilyApp
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    assert i18n.current_language() == "zh"


def test_init_falls_back_to_zh_when_stored_lang_missing_from_catalogs(svc):
    """Stored lang code not in bundled catalogs → silent fallback to "zh", not crash."""
    set_pref(svc.db, "language", "klingon")
    from polily.tui.app import PolilyApp
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    # init_i18n falls back to FALLBACK_LANG when default isn't loaded
    assert i18n.current_language() == "zh"


@pytest.mark.asyncio
async def test_toggle_action_cycles_lang_persists_and_publishes(svc):
    from polily.tui.app import PolilyApp
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    received = []
    svc.event_bus.subscribe(TOPIC_LANGUAGE_CHANGED, received.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        # Starting state should be "zh"
        assert i18n.current_language() == "zh"
        await app.action_toggle_language()
        await pilot.pause()

    assert i18n.current_language() == "en"
    # Persisted to DB
    assert get_pref(svc.db, "language") == "en"
    # Bus event delivered
    assert received == [{"language": "en"}]


@pytest.mark.asyncio
async def test_toggle_wraps_back_to_starting_language(svc):
    """Cycling through every language brings us back to the starting point."""
    from polily.tui.app import PolilyApp
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        langs = i18n.available_languages()
        start = i18n.current_language()
        for _ in range(len(langs)):
            await app.action_toggle_language()
        assert i18n.current_language() == start
