"""CompanionsView — sidebar's 9th entry, cross-promotes polily-plugin
and (future) Claude Code skill packs scoped to polily lifecycle.

CompanionsView is a static read-only Markdown view (analogous to
ChangelogView): no service / db needed, no network fetch, no
interactive widgets. The single source of truth is the
`companions.body_md` i18n key, which carries the full Markdown body.

Tests cover:
  1. Sidebar exposes `companions` as the 10th menu item (after changelog)
  2. MENU_ICONS maps `companions` to the new ICON_COMPANION glyph
  3. MainScreen has `Binding("9", "show_companions")` + MENU_ORDER ends with companions
  4. View renders the i18n title + Markdown body
  5. Markdown body contains the polily-plugin pitch + install commands
  6. i18n catalogs (en + zh) both define non-default content
  7. Live language switch (TOPIC_LANGUAGE_CHANGED) re-applies title + body
     in-place without remount
"""
from __future__ import annotations

import pytest
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Markdown

from polily.tui.icons import ICON_COMPANION
from polily.tui.widgets.sidebar import MENU_ICONS, Sidebar, SidebarItem

# ---------------------------------------------------------------------------
# 1-2. Sidebar wiring (sync tests — no event loop needed)
# ---------------------------------------------------------------------------


def test_menu_icons_includes_companions():
    """MENU_ICONS must map 'companions' to the fa-plug glyph."""
    assert "companions" in MENU_ICONS, (
        "MENU_ICONS missing 'companions' — sidebar entry would render glyph-less"
    )
    assert MENU_ICONS["companions"] == ICON_COMPANION


def test_sidebar_compose_emits_companions_as_last_menu_item():
    """`companions` lives after `changelog` (the last existing menu item).

    Order matters — Sidebar renders compose() output top-to-bottom, and
    the numeric key bindings (0-8 existing, 9 = companions) line up
    with this order.
    """
    sidebar = Sidebar()
    items = [item for item in sidebar.compose() if isinstance(item, SidebarItem)]
    menu_ids = [item.menu_id for item in items]
    assert menu_ids == [
        "tasks", "monitor", "paper", "wallet",
        "history", "archive", "config", "strategy", "changelog",
        "companions",
    ], f"sidebar menu order drifted: {menu_ids!r}"


# ---------------------------------------------------------------------------
# 3. MainScreen binding wiring (sync test — pure structural assertions)
# ---------------------------------------------------------------------------


def test_main_screen_has_key_9_binding_and_companions_in_menu_order():
    """MainScreen must have:
      - Binding key '9' → action 'show_companions'
      - MENU_ORDER's last element is 'companions' (matches sidebar compose order)
      - `action_show_companions` callable exists on the class
    """
    from polily.tui.screens.main import MainScreen

    # Binding key 9 → show_companions action
    key_to_action = {b.key: b.action for b in MainScreen.BINDINGS}
    assert key_to_action.get("9") == "show_companions", (
        f"MainScreen.BINDINGS missing key='9' -> show_companions; "
        f"key 9 currently bound to: {key_to_action.get('9')!r}"
    )

    # MENU_ORDER ends with companions
    assert MainScreen.MENU_ORDER[-1] == "companions", (
        f"MainScreen.MENU_ORDER last element should be 'companions'; "
        f"got: {MainScreen.MENU_ORDER!r}"
    )

    # Action method exists (called by Textual when key 9 fires)
    assert hasattr(MainScreen, "action_show_companions"), (
        "MainScreen missing action_show_companions method — "
        "the Binding declaration won't resolve at key press"
    )


# ---------------------------------------------------------------------------
# 4. View renders (async tests — actual Textual mount/compose)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_companions_view_renders_zone_with_markdown():
    """View mounts: PolilyZone wrapper + Markdown widget inside VerticalScroll."""
    from polily.tui.views.companions import CompanionsView

    class T(App):
        def compose(self):
            yield CompanionsView()

    async with T().run_test() as pilot:
        view = pilot.app.query_one(CompanionsView)
        # Outer scroll wrapper exists (so long content is scrollable)
        scrolls = view.query(VerticalScroll)
        assert len(list(scrolls)) >= 1, (
            "CompanionsView must wrap content in VerticalScroll to avoid "
            "clipping the long body on small terminals"
        )
        # Markdown widget mounted (this is the actual content host)
        md = view.query_one("#companions-md", Markdown)
        assert md is not None


# ---------------------------------------------------------------------------
# 5-6. i18n: body_md content + en/zh both non-default
# ---------------------------------------------------------------------------


def test_companions_body_md_contains_polily_plugin_pitch_in_both_languages():
    """body_md must contain the polily-plugin name + install commands in
    both en and zh catalogs. Catches "key exists but is empty / stub" and
    "translator forgot the install block".
    """
    from polily.tui.i18n import set_language, t

    set_language("en")
    en = t("companions.body_md")
    assert "polily-plugin" in en
    assert "/plugin marketplace add ShiyuCheng2018/polily-plugin" in en, (
        "en body_md missing the install command — users wouldn't see how to install"
    )
    assert "/plugin install polily@polily-plugin" in en
    assert "/reload-plugins" in en

    set_language("zh")
    zh = t("companions.body_md")
    assert "polily-plugin" in zh
    assert "/plugin marketplace add ShiyuCheng2018/polily-plugin" in zh, (
        "zh body_md missing the install command — same regression as en above"
    )
    # zh-specific copy markers — guards against translator stubbing zh = en
    assert any(marker in zh for marker in ("示例", "扩展", "安装")), (
        f"zh body_md looks like en placeholder — got: {zh[:200]!r}"
    )

    # Restore for other tests
    set_language("en")


def test_companions_zone_title_differs_between_languages():
    """zone title key must have distinct en + zh values (no key-fallback)."""
    from polily.tui.i18n import set_language, t

    set_language("en")
    en_title = t("companions.title.zone")
    set_language("zh")
    zh_title = t("companions.title.zone")

    assert en_title != zh_title, (
        f"companions.title.zone collapsed to same value in en + zh "
        f"({en_title!r}) — likely a missing catalog entry"
    )
    assert en_title != "companions.title.zone", "en title falls back to key string"
    assert zh_title != "companions.title.zone", "zh title falls back to key string"

    set_language("en")


def test_companions_sidebar_label_differs_between_languages():
    """sidebar.companions label key must have distinct en + zh values."""
    from polily.tui.i18n import set_language, t

    set_language("en")
    en_label = t("sidebar.companions")
    set_language("zh")
    zh_label = t("sidebar.companions")

    assert en_label != zh_label, (
        f"sidebar.companions collapsed to same value in en + zh ({en_label!r})"
    )
    assert en_label != "sidebar.companions"
    assert zh_label != "sidebar.companions"

    set_language("en")


# ---------------------------------------------------------------------------
# 7. Live language switch updates mounted widget without remount
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_language_switch_updates_markdown_body():
    """Same pattern as wallet.py / event_detail.py / archived_events.py /
    strategy.py: subscribe to TOPIC_LANGUAGE_CHANGED on mount, refresh
    Markdown body in-place. Without this, content freezes at whatever
    language was loaded when CompanionsView was first mounted.

    We assert on `Markdown.source` (public property reflecting the latest
    update() call) rather than the PolilyZone title Static — Textual's
    Static doesn't expose `renderable` as a public attribute, so probing
    it is API-fragile. The handler updates both title + body in the same
    branch, so a passing Markdown assertion transitively proves the
    handler ran.
    """
    from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
    from polily.tui.i18n import set_language, t
    from polily.tui.views.companions import CompanionsView

    set_language("en")
    en_body = t("companions.body_md")

    class T(App):
        def compose(self):
            yield CompanionsView()

    async with T().run_test() as pilot:
        view = pilot.app.query_one(CompanionsView)
        md = view.query_one("#companions-md", Markdown)

        # Sanity: en mode renders the en body at mount time
        assert md.source == en_body, (
            f"Markdown.source at mount differs from en body_md "
            f"(starts with {md.source[:60]!r} vs expected {en_body[:60]!r})"
        )

        # Switch language + publish event (mimics action_toggle_language)
        set_language("zh")
        zh_body = t("companions.body_md")
        assert zh_body != en_body, "zh body_md not actually different from en (test setup issue)"
        get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": "zh"})
        await pilot.pause()

        # Markdown body should reflect the zh catalog entry, in-place
        assert md.source == zh_body, (
            f"Markdown body still {md.source[:60]!r} after language switch — "
            f"CompanionsView is not subscribing to TOPIC_LANGUAGE_CHANGED"
        )

    # Restore for other tests
    set_language("en")
