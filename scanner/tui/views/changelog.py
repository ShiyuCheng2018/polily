"""ChangelogView: renders CHANGELOG.md as Markdown inside a PolilyZone.

v0.8.0 addition. The changelog ships inside the wheel via `pyproject.toml`
`tool.hatch.build.targets.wheel.force-include`, so both dev-install and
pip-install paths resolve `CHANGELOG.md` via `importlib.resources`. Dev
takes precedence so a live edit shows up on `r` refresh without
reinstalling the package.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown

from scanner.tui.bindings import NAV_BINDINGS
from scanner.tui.icons import ICON_CHANGELOG
from scanner.tui.widgets.polily_zone import PolilyZone


def _load_changelog() -> str:
    """Return CHANGELOG.md text, falling back to a short error markdown.

    Resolution order:
      1. Repo root (dev checkout) — four levels up from this file.
      2. Packaged resource — `importlib.resources.files("scanner")` path
         reached via the `force-include` rule in pyproject.toml, which
         copies CHANGELOG.md into `scanner/CHANGELOG.md` at wheel build.
    """
    # Dev path — live editing while running from repo
    dev_path = Path(__file__).resolve().parents[3] / "CHANGELOG.md"
    if dev_path.exists():
        try:
            return dev_path.read_text(encoding="utf-8")
        except Exception as e:
            return f"# 读取 CHANGELOG.md 失败\n\n`{type(e).__name__}: {e}`"

    # Installed path — look inside the scanner package itself
    try:
        from importlib.resources import files
        packaged = files("scanner") / "CHANGELOG.md"
        if packaged.is_file():
            return packaged.read_text(encoding="utf-8")
    except Exception as e:
        return f"# 读取打包 CHANGELOG 失败\n\n`{type(e).__name__}: {e}`"

    return (
        "# 找不到 CHANGELOG.md\n\n"
        "源码仓库根目录的 CHANGELOG.md 不存在，打包资源里也没有。\n\n"
        "完整日志: https://github.com/ShiyuCheng2018/polily/blob/master/CHANGELOG.md"
    )


class ChangelogView(Widget):
    """Render CHANGELOG.md with Textual's built-in Markdown widget."""

    BINDINGS = [
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    ChangelogView { height: 1fr; }
    ChangelogView > VerticalScroll { height: 1fr; }
    ChangelogView > VerticalScroll > PolilyZone { height: 1fr; }
    ChangelogView Markdown { padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            with PolilyZone(title=f"{ICON_CHANGELOG} 更新日志", id="changelog-zone"):
                yield Markdown(_load_changelog(), id="changelog-md")

    def action_refresh(self) -> None:
        """Manual refresh — re-read CHANGELOG.md from disk + re-render.

        Useful during dev when editing CHANGELOG.md in the repo — `r`
        pulls the latest content without restarting the TUI.
        """
        try:
            self.query_one("#changelog-md", Markdown).update(_load_changelog())
        except Exception:
            # Fall back to full recompose if the Markdown widget is
            # missing (shouldn't happen but defensive).
            self.recompose()
