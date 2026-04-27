"""Tests for polily.tui.widgets.i18n_footer.I18nFooter.

Focus on the description-resolution logic + event subscription bookkeeping.
The actual recompose-on-event behavior is hard to test without a running
Textual app, so we test the seam (resolver function) directly and rely on
manual TUI verification for the integration path.
"""
from __future__ import annotations

import pytest

from polily.core.events import TOPIC_LANGUAGE_CHANGED, EventBus
from polily.tui import i18n
from polily.tui.widgets.i18n_footer import resolve_description


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def test_resolve_description_uses_catalog_for_known_action():
    i18n.init_i18n(
        {"zh": {"binding.quit": "退出"}, "en": {"binding.quit": "Quit"}},
        default="zh",
    )
    assert resolve_description("quit", fallback="退出") == "退出"
    i18n.set_language("en")
    assert resolve_description("quit", fallback="退出") == "Quit"


def test_resolve_description_falls_back_when_catalog_missing_key():
    i18n.init_i18n({"zh": {}, "en": {}}, default="zh")
    assert resolve_description("foobar", fallback="raw fallback") == "raw fallback"


def test_resolve_description_empty_action_returns_fallback():
    i18n.init_i18n({"zh": {"binding.": "should not match"}}, default="zh")
    assert resolve_description("", fallback="fb") == "fb"


def test_subscription_round_trip():
    """Verify bus.subscribe/unsubscribe symmetry — guards against handler leaks
    when widgets mount/unmount repeatedly."""
    bus = EventBus()
    received = []

    def handler(payload):
        received.append(payload)

    bus.subscribe(TOPIC_LANGUAGE_CHANGED, handler)
    bus.publish(TOPIC_LANGUAGE_CHANGED, {"language": "en"})
    assert received == [{"language": "en"}]

    bus.unsubscribe(TOPIC_LANGUAGE_CHANGED, handler)
    bus.publish(TOPIC_LANGUAGE_CHANGED, {"language": "zh"})
    # second publish should not deliver
    assert received == [{"language": "en"}]
