"""i18n smoke tests for PR-5 component migrations.

These cover the rendering helpers / module-level functions that take a
language-dependent path. Component-Widget rendering is exercised
indirectly via the existing event_detail and score_result smoke tests.
"""
from __future__ import annotations

import pytest

from polily.core.lifecycle import EventState, MarketState
from polily.tui import i18n
from polily.tui.lifecycle_labels import (
    event_state_label_i18n,
    market_state_label_i18n,
    settled_winner_suffix_i18n,
)


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


class _FakeMarket:
    def __init__(self, resolved_outcome: str | None = None):
        self.resolved_outcome = resolved_outcome


def test_market_state_label_flips_on_language_change():
    assert market_state_label_i18n(MarketState.TRADING) == "交易中"
    i18n.set_language("en")
    assert market_state_label_i18n(MarketState.TRADING) == "Trading"


def test_event_state_label_flips_on_language_change():
    assert event_state_label_i18n(EventState.ACTIVE) == "进行中"
    i18n.set_language("en")
    assert event_state_label_i18n(EventState.ACTIVE) == "Active"


def test_settled_winner_suffix_translates_outcomes():
    yes = _FakeMarket("yes")
    no = _FakeMarket("no")
    split = _FakeMarket("split")
    void = _FakeMarket("void")
    none = _FakeMarket(None)

    # zh
    assert settled_winner_suffix_i18n(yes) == " YES 获胜"
    assert settled_winner_suffix_i18n(none) == ""

    # en
    i18n.set_language("en")
    assert settled_winner_suffix_i18n(yes) == " YES won"
    assert settled_winner_suffix_i18n(no) == " NO won"
    assert settled_winner_suffix_i18n(split) == " Split"
    assert settled_winner_suffix_i18n(void) == " Void"
    assert settled_winner_suffix_i18n(none) == ""


def test_movement_label_i18n_known_label():
    from polily.tui.components.movement_sparkline import movement_label_i18n
    assert movement_label_i18n("consensus") == "共识异动"
    i18n.set_language("en")
    assert movement_label_i18n("consensus") == "Consensus"


def test_movement_label_i18n_unknown_label_returned_as_is():
    from polily.tui.components.movement_sparkline import movement_label_i18n
    # No catalog entry → return label as-is, never the key string
    assert movement_label_i18n("frobnicated") == "frobnicated"
