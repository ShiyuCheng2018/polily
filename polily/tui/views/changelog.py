"""ChangelogView: renders CHANGELOG.md as Markdown inside a PolilyZone.

v0.8.0 addition. The changelog ships inside the wheel via `pyproject.toml`
`tool.hatch.build.targets.wheel.force-include`, so both dev-install and
pip-install paths resolve `CHANGELOG.md` via `importlib.resources`. Dev
takes precedence so a live edit shows up on `r` refresh without
reinstalling the package.

v0.8.5 addition: page is now scrollable (previously the inner
`PolilyZone { height: 1fr }` rule clipped long changelogs), and a
version header shows `当前版本 vX · 最新稳定版 vY` — the latter is
fetched asynchronously from GitHub releases on mount so the UI doesn't
block.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.i18n import t
from polily.tui.icons import ICON_CHANGELOG
from polily.tui.widgets.polily_zone import PolilyZone

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/ShiyuCheng2018/polily/releases/latest"
)
_FETCH_TIMEOUT_SECONDS = 3.0


def _load_changelog() -> str:
    """Return CHANGELOG.md text, falling back to a short error markdown.

    Resolution order:
      1. Repo root (dev checkout) — four levels up from this file.
      2. Packaged resource — `importlib.resources.files("polily")` path
         reached via the `force-include` rule in pyproject.toml, which
         copies CHANGELOG.md into `polily/CHANGELOG.md` at wheel build.
    """
    dev_path = Path(__file__).resolve().parents[3] / "CHANGELOG.md"
    if dev_path.exists():
        try:
            return dev_path.read_text(encoding="utf-8")
        except Exception as e:
            return t("changelog.error.read_failed", detail=f"{type(e).__name__}: {e}")

    try:
        from importlib.resources import files
        packaged = files("polily") / "CHANGELOG.md"
        if packaged.is_file():
            return packaged.read_text(encoding="utf-8")
    except Exception as e:
        return t("changelog.error.read_packaged_failed", detail=f"{type(e).__name__}: {e}")

    return t("changelog.error.not_found")


def _fetch_latest_release_tag() -> str:
    """Blocking GET to GitHub releases/latest. Returns tag_name or a
    human-readable error phrase. Meant to be called from a thread worker
    so the TUI event loop isn't blocked."""
    import httpx
    try:
        with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS) as client:
            r = client.get(GITHUB_LATEST_RELEASE_URL)
            r.raise_for_status()
            tag = r.json().get("tag_name")
            return tag if tag else "?"
    except Exception:
        return t("changelog.unable_to_fetch")


def _format_version_line(current: str, latest: str) -> str:
    """Render the version header line. Kept as a module-level helper so
    tests can assert the exact copy without instantiating the widget."""
    return t("changelog.version_line", current=current, latest=latest)


class ChangelogView(Widget):
    """Render CHANGELOG.md with Textual's built-in Markdown widget.

    Scrolling: the outer `VerticalScroll` handles overflow. Inner
    PolilyZone is sized `height: auto` so it grows with its Markdown
    child — a `height: 1fr` there would clamp the zone to the viewport
    and clip long changelogs (this was the v0.8.5 fix).
    """

    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time, so the zh strings below are only fallbacks (Textual's
    # Binding.make_bindings sets show=False for empty descriptions).
    BINDINGS = [
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    ChangelogView { height: 1fr; }
    ChangelogView > VerticalScroll { height: 1fr; }
    /* height: auto (was 1fr) — lets PolilyZone grow with Markdown content
       so the outer VerticalScroll gets something taller than the viewport
       to actually scroll. */
    ChangelogView > VerticalScroll > PolilyZone { height: auto; }
    ChangelogView #changelog-versions {
        padding: 0 1 1 1;
        color: $text-muted;
    }
    ChangelogView Markdown { padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        from polily import __version__ as current

        with VerticalScroll():
            with PolilyZone(title=f"{ICON_CHANGELOG} {t('changelog.title.zone')}", id="changelog-zone"):
                yield Static(
                    _format_version_line(current, t("changelog.fetching")),
                    id="changelog-versions",
                )
                yield Markdown(_load_changelog(), id="changelog-md")

    def on_mount(self) -> None:
        """Kick off a background fetch for the latest stable release tag.

        Thread worker so the 3s HTTP call doesn't block the UI. On return
        the Static is updated via `call_from_thread` (required — updates
        from a non-UI thread must be marshaled back to the event loop).
        """
        self.run_worker(self._fetch_and_update_version, thread=True, exclusive=True)
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        get_event_bus().unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        """Re-render zone title + version line + markdown body. The
        Markdown widget can be `update`d in place; the PolilyZone title
        is a child Static reachable by class selector."""
        with contextlib.suppress(Exception):
            self.query_one("#changelog-zone .polily-zone-title", Static).update(
                f"{ICON_CHANGELOG} {t('changelog.title.zone')}",
            )
            self.query_one("#changelog-md", Markdown).update(_load_changelog())
            # Re-render version line in case it carries the i18n "fetching"
            # placeholder (otherwise the worker's _apply_version handles it).
            from polily import __version__ as current
            self.query_one("#changelog-versions", Static).update(
                _format_version_line(current, t("changelog.fetching")),
            )
            # Kick off a fresh fetch so "Unavailable" / "无法获取" updates too.
            self.run_worker(self._fetch_and_update_version, thread=True, exclusive=True)

    def _fetch_and_update_version(self) -> None:
        latest = _fetch_latest_release_tag()
        self.app.call_from_thread(self._apply_version, latest)

    def _apply_version(self, latest: str) -> None:
        from polily import __version__ as current
        with contextlib.suppress(Exception):
            self.query_one("#changelog-versions", Static).update(
                _format_version_line(current, latest),
            )

    def action_refresh(self) -> None:
        """Manual refresh — re-read CHANGELOG.md + re-query latest release."""
        try:
            self.query_one("#changelog-md", Markdown).update(_load_changelog())
        except Exception:
            self.refresh(recompose=True)
            return

        from polily import __version__ as current
        with contextlib.suppress(Exception):
            self.query_one("#changelog-versions", Static).update(
                _format_version_line(current, t("changelog.fetching")),
            )
        self.run_worker(self._fetch_and_update_version, thread=True, exclusive=True)
