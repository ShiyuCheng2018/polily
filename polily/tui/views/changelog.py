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

from polily.tui.bindings import NAV_BINDINGS
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
            return f"# 读取 CHANGELOG.md 失败\n\n`{type(e).__name__}: {e}`"

    try:
        from importlib.resources import files
        packaged = files("polily") / "CHANGELOG.md"
        if packaged.is_file():
            return packaged.read_text(encoding="utf-8")
    except Exception as e:
        return f"# 读取打包 CHANGELOG 失败\n\n`{type(e).__name__}: {e}`"

    return (
        "# 找不到 CHANGELOG.md\n\n"
        "源码仓库根目录的 CHANGELOG.md 不存在，打包资源里也没有。\n\n"
        "完整日志: https://github.com/ShiyuCheng2018/polily/blob/master/CHANGELOG.md"
    )


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
        return "无法获取"


def _format_version_line(current: str, latest: str) -> str:
    """Render the version header line. Kept as a module-level helper so
    tests can assert the exact copy without instantiating the widget."""
    return f"当前版本: v{current} · 最新稳定版: {latest}"


class ChangelogView(Widget):
    """Render CHANGELOG.md with Textual's built-in Markdown widget.

    Scrolling: the outer `VerticalScroll` handles overflow. Inner
    PolilyZone is sized `height: auto` so it grows with its Markdown
    child — a `height: 1fr` there would clamp the zone to the viewport
    and clip long changelogs (this was the v0.8.5 fix).
    """

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
            with PolilyZone(title=f"{ICON_CHANGELOG} 更新日志", id="changelog-zone"):
                yield Static(
                    _format_version_line(current, "查询中..."),
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
            self.recompose()
            return

        from polily import __version__ as current
        with contextlib.suppress(Exception):
            self.query_one("#changelog-versions", Static).update(
                _format_version_line(current, "查询中..."),
            )
        self.run_worker(self._fetch_and_update_version, thread=True, exclusive=True)
