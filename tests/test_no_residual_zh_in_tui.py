"""CI gate: catch new Chinese string literals leaking into TUI source.

Allows known fallbacks (BINDINGS zh defaults that I18nFooter overrides at
runtime, internal column keys that happen to be Chinese for legacy reasons)
via an explicit allowlist.

If you intentionally add a Chinese string to a TUI file, either:
  - Wrap it in t("some.catalog.key") and add the key to both
    catalogs/zh.json and catalogs/en.json, or
  - Add the file:line to ALLOWLIST below with a one-line reason.

The goal is "no silent zh leaks", not "zero zh anywhere" — fallbacks and
internal-key strings are deliberate and harmless.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# Files where zh string literals are intentional (fallbacks, internal keys
# that happen to be CN-coded, etc.). Each entry is the relative path under
# polily/. Keep the list short — the catalog approach should be the default.
_ALLOWLIST_FILES = {
    # Docstring-only references (no user-facing strings):
    "tui/components/position_panel.py",
    "tui/service.py",
    "tui/utils.py",
    "tui/widgets/buy_sell_action_row.py",

    # I18nFooter renders binding labels via t(f"binding.{action}") at compose
    # time; the zh strings in BINDINGS lists are only fallbacks (Textual sets
    # show=False on empty descriptions, so we can't blank them).
    "tui/bindings.py",
    "tui/views/wallet.py",          # only BINDINGS fallbacks remain
    "tui/views/event_detail.py",    # only BINDINGS fallbacks remain
    "tui/views/score_result.py",    # only BINDINGS fallbacks remain
    "tui/views/scan_log.py",        # BINDINGS fallbacks + docstring zone names
    "tui/views/paper_status.py",    # BINDINGS fallback + legacy "现价" column key
    "tui/views/monitor_list.py",    # BINDINGS fallbacks
    "tui/views/archived_events.py", # BINDINGS fallbacks
    "tui/views/changelog.py",       # BINDINGS fallback
    "tui/views/history.py",         # BINDINGS fallback
    "tui/views/scan_modals.py",     # BINDINGS fallback (escape→cancel "取消")
    "tui/views/monitor_modals.py",  # BINDINGS fallback (escape→keep "继续监控")
    "tui/views/wallet_modals.py",   # BINDINGS fallbacks
    "tui/views/trade_dialog.py",    # BINDINGS fallback
    # Comments / docstrings only
    "tui/components/sub_market_table.py",
    "tui/components/event_kpi.py",
    "tui/widgets/_datatable_i18n.py",
    "tui/widgets/quick_amount_row.py",
    "tui/widgets/polily_zone.py",
    "tui/screens/main.py",          # docstring + 待办 in comment only
    "tui/monitor_format.py",        # docstring zh references only
}

# Pattern: any string literal containing a CJK Unified Ideograph.
_ZH_LITERAL = re.compile(r'["\']([^"\']*[一-鿿][^"\']*)["\']')


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return [(line_no, snippet)] for every line containing a zh literal,
    skipping pure-comment lines."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if _ZH_LITERAL.search(line):
            hits.append((i, line.strip()))
    return hits


def test_no_unallowlisted_zh_string_literals_in_tui():
    """Walk polily/tui/**.py — every zh string literal must be inside an
    allowlisted file."""
    tui_root = Path(__file__).resolve().parent.parent / "polily" / "tui"
    leaks: list[str] = []
    for path in sorted(tui_root.rglob("*.py")):
        rel = path.relative_to(tui_root.parent).as_posix()
        if rel in _ALLOWLIST_FILES:
            continue
        hits = _scan_file(path)
        for line_no, snippet in hits:
            leaks.append(f"  {rel}:{line_no}  {snippet[:120]}")

    if leaks:
        pytest.fail(
            "Found {n} zh string literal(s) leaking into TUI source. Either "
            "wrap them in t('catalog.key') (preferred) or add the file to "
            "_ALLOWLIST_FILES with a reason:\n{rows}".format(
                n=len(leaks), rows="\n".join(leaks),
            )
        )
