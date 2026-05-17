"""CompanionsView: persistent ambient surface advertising polily's
Claude Code skill packs and (future) companion tools.

v0.12.x addition. Modelled on `ChangelogView` — static read-only
Markdown view, no service / db / network. Content lives in the
`companions.body_md` i18n key so en + zh are first-class.

Future companion tools (Discord webhook, Telegram bot, additional
Claude Code skills) extend this surface by adding cards to the same
Markdown body — no new TUI scaffolding needed per tool.
"""
from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.i18n import t
from polily.tui.icons import ICON_COMPANION
from polily.tui.widgets.polily_zone import PolilyZone


class CompanionsView(Widget):
    """Render the companions catalog (polily-plugin + future tools).

    No constructor args — the entire content is i18n-driven from the
    `companions.body_md` key. PolilyService isn't required since the
    view doesn't read user state.
    """

    BINDINGS = [
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    CompanionsView { height: 1fr; }
    CompanionsView > VerticalScroll { height: 1fr; }
    /* height: auto so the inner PolilyZone grows with the Markdown body
       (mirrors the ChangelogView v0.8.5 fix — fixed-height zone would
       clip long content). */
    CompanionsView > VerticalScroll > PolilyZone { height: auto; }
    CompanionsView Markdown { padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            with PolilyZone(
                title=f"{ICON_COMPANION} {t('companions.title.zone')}",
                id="companions-zone",
            ):
                yield Markdown(t("companions.body_md"), id="companions-md")

    def on_mount(self) -> None:
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        get_event_bus().unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        """Refresh zone title + Markdown body in-place after F2 lang switch.

        Same pattern as ChangelogView / StrategyView — mutate the
        mounted widgets directly rather than re-composing, which
        preserves scroll position and avoids a flash.
        """
        with contextlib.suppress(Exception):
            self.query_one(
                "#companions-zone .polily-zone-title", Static,
            ).update(
                f"{ICON_COMPANION} {t('companions.title.zone')}",
            )
            self.query_one("#companions-md", Markdown).update(
                t("companions.body_md"),
            )
