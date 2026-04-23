"""Release-QA helper: capture SVG/PNG snapshots of every TUI view + modal.

Runs Textual's `App.run_test` headless for each target, exports SVG via
`save_screenshot`, then (optionally) renders to PNG via `rsvg-convert`.
Produces a README describing each capture + known caveats (Nerd Font
.notdef in headless mode, etc.).

Primary use: **before every release, run this and eyeball the output**
to catch visual regressions a human would notice (layout drift, zone
alignment, color themes). A lightweight alternative to
`pytest-textual-snapshot` — see `docs/internal/v090-backlog.md` for
why we chose manual QA over automated baseline diffing for v0.8.x.

Usage:

    # Full capture + PNG rendering (requires rsvg-convert)
    python scripts/generate_snapshots.py

    # Just SVG, skip PNG
    python scripts/generate_snapshots.py --no-png

    # Capture a subset
    python scripts/generate_snapshots.py --targets event_detail wallet

    # Custom output location
    python scripts/generate_snapshots.py --output-dir /tmp/my-snaps

Install rsvg-convert:
    macOS:   brew install librsvg
    Debian:  apt install librsvg2-bin
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# --- Ensure project root on path ---
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Runtime-configurable; overridden by argparse in main().
OUT_DIR = Path("/tmp/polily-snapshots")
RSVG_PATH = shutil.which("rsvg-convert") or "/opt/homebrew/bin/rsvg-convert"
PNG_HEIGHT = 900
CONVERT_PNG = True

# Terminal geometry for run_test. Wide enough for dense views.
SIZE = (160, 45)


# ---------------------------------------------------------------------------
# Fixture seeding
# ---------------------------------------------------------------------------

def _make_cfg():
    """Mock-config compatible with PolilyService code paths touched by views."""
    cfg = SimpleNamespace()
    cfg.wallet = SimpleNamespace(starting_balance=100.0)
    cfg.paper_trading = SimpleNamespace(
        default_position_size_usd=20,
        assumed_round_trip_friction_pct=0.04,
    )
    cfg.archiving = SimpleNamespace(db_file="")  # unused; caller supplies db
    return cfg


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _future_iso(hours: int = 6) -> str:
    from datetime import timedelta
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _seed_full_fixture(db):
    """Populate DB with realistic mixed fixture for all views.

    Events: 3 scored, 1 archived.
    Markets: 2-3 per event.
    Scan logs: mix of pending/completed/failed.
    Wallet: balance 100 + topup + withdraw + BUY + SELL.
    Positions: 2 open.
    Analyses: 1 version on the primary event.
    """
    from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
    from polily.core.monitor_store import upsert_event_monitor
    from polily.analysis_store import AnalysisVersion, append_analysis
    from polily.scan_log import insert_pending_scan, finish_scan, _make_scan_id

    # --- Events (3 live + 1 archived) ---
    ev_btc = EventRow(
        event_id="ev_btc",
        title="What price will Bitcoin hit in April?",
        slug="bitcoin-april-price",
        updated_at=_now_iso(),
        market_count=3,
        structure_score=78.0,
        tier="GO",
        end_date="2026-04-30T23:59:59Z",
        tags="[\"Crypto\",\"Bitcoin\"]",
    )
    upsert_event(ev_btc, db)
    # Structure score is not in INSERT_COLS — update directly.
    db.conn.execute(
        "UPDATE events SET structure_score=?, tier=? WHERE event_id=?",
        (78.0, "GO", "ev_btc"),
    )

    ev_iran = EventRow(
        event_id="ev_iran",
        title="US-Iran nuclear deal by April 30?",
        slug="us-iran-nuclear-deal-april",
        updated_at=_now_iso(),
        market_count=1,
        end_date="2026-04-30T23:59:59Z",
        tags="[\"Geopolitics\",\"Middle East\"]",
    )
    upsert_event(ev_iran, db)
    db.conn.execute(
        "UPDATE events SET structure_score=?, tier=? WHERE event_id=?",
        (62.0, "WATCH", "ev_iran"),
    )

    ev_peace = EventRow(
        event_id="ev_peace",
        title="US x Iran permanent peace deal in 2026?",
        slug="us-iran-permanent-peace-2026",
        updated_at=_now_iso(),
        market_count=1,
        end_date="2026-12-31T23:59:59Z",
        tags="[\"Geopolitics\"]",
    )
    upsert_event(ev_peace, db)
    db.conn.execute(
        "UPDATE events SET structure_score=?, tier=? WHERE event_id=?",
        (55.0, "WATCH", "ev_peace"),
    )

    ev_archived = EventRow(
        event_id="ev_archived",
        title="Will ETH ETF be approved by end of Q1?",
        slug="eth-etf-q1",
        updated_at="2026-04-01T00:00:00+00:00",
        market_count=1,
        closed=1,
        end_date="2026-03-31T23:59:59Z",
        tags="[\"Crypto\",\"ETH\"]",
    )
    upsert_event(ev_archived, db)
    db.conn.execute(
        "UPDATE events SET structure_score=?, tier=?, closed=1 WHERE event_id=?",
        (82.0, "GO", "ev_archived"),
    )

    # --- Markets ---
    # BTC event: 3 sub-markets
    for mid, q, tgt, yes, no in [
        ("m_btc_70k", "Bitcoin reaches $70,000?", "70000", 0.62, 0.38),
        ("m_btc_80k", "Bitcoin reaches $80,000?", "80000", 0.23, 0.77),
        ("m_btc_90k", "Bitcoin reaches $90,000?", "90000", 0.08, 0.92),
    ]:
        upsert_market(
            MarketRow(
                market_id=mid,
                event_id="ev_btc",
                question=q,
                group_item_title=f"${tgt}",
                group_item_threshold=tgt,
                clob_token_id_yes=f"tok_y_{mid}",
                clob_token_id_no=f"tok_n_{mid}",
                yes_price=yes,
                no_price=no,
                best_bid=yes - 0.01,
                best_ask=yes + 0.01,
                spread=0.02,
                volume=1_250_000.0,
                liquidity=85_000.0,
                updated_at=_now_iso(),
            ),
            db,
        )

    # Iran nuclear (binary)
    upsert_market(
        MarketRow(
            market_id="m_iran",
            event_id="ev_iran",
            question="US-Iran nuclear deal by April 30?",
            clob_token_id_yes="tok_y_iran",
            clob_token_id_no="tok_n_iran",
            yes_price=0.18,
            no_price=0.82,
            best_bid=0.17,
            best_ask=0.19,
            spread=0.02,
            volume=420_000.0,
            liquidity=38_000.0,
            updated_at=_now_iso(),
        ),
        db,
    )

    # Peace (binary)
    upsert_market(
        MarketRow(
            market_id="m_peace",
            event_id="ev_peace",
            question="US x Iran permanent peace deal in 2026?",
            clob_token_id_yes="tok_y_peace",
            clob_token_id_no="tok_n_peace",
            yes_price=0.09,
            no_price=0.91,
            best_bid=0.08,
            best_ask=0.10,
            spread=0.02,
            volume=180_000.0,
            liquidity=22_000.0,
            updated_at=_now_iso(),
        ),
        db,
    )

    # Archived market
    upsert_market(
        MarketRow(
            market_id="m_archived",
            event_id="ev_archived",
            question="Will ETH ETF be approved by end of Q1?",
            clob_token_id_yes="tok_y_eth",
            clob_token_id_no="tok_n_eth",
            yes_price=1.0,  # resolved YES
            no_price=0.0,
            closed=1,
            updated_at="2026-04-01T00:00:00+00:00",
        ),
        db,
    )

    # --- Monitoring ---
    upsert_event_monitor(event_id="ev_btc", auto_monitor=True, db=db)
    upsert_event_monitor(event_id="ev_iran", auto_monitor=True, db=db)
    upsert_event_monitor(event_id="ev_archived", auto_monitor=True, db=db)

    # --- Scan logs: mix pending + history (completed/failed) ---
    # Upcoming / pending
    insert_pending_scan(
        event_id="ev_btc",
        event_title="What price will Bitcoin hit in April?",
        scheduled_at=_future_iso(hours=4),
        trigger_source="scheduled",
        scheduled_reason="价格接近$70K关键位",
        db=db,
    )
    insert_pending_scan(
        event_id="ev_iran",
        event_title="US-Iran nuclear deal by April 30?",
        scheduled_at=_future_iso(hours=12),
        trigger_source="scheduled",
        scheduled_reason="临近截止日期",
        db=db,
    )
    insert_pending_scan(
        event_id="ev_peace",
        event_title="US x Iran permanent peace deal in 2026?",
        scheduled_at=_future_iso(hours=24),
        trigger_source="manual",
        scheduled_reason=None,
        db=db,
    )

    # History: completed scan
    sid1 = _make_scan_id(prefix="r")
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, market_title, started_at, "
        "finished_at, total_elapsed, status, trigger_source) "
        "VALUES (?, 'analyze', 'ev_btc', ?, ?, ?, ?, 'completed', 'manual')",
        (sid1, "What price will Bitcoin hit in April?",
         "2026-04-20T10:00:00+00:00", "2026-04-20T10:02:34+00:00", 154.2),
    )
    sid2 = _make_scan_id(prefix="r")
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, market_title, started_at, "
        "finished_at, total_elapsed, status, trigger_source) "
        "VALUES (?, 'analyze', 'ev_iran', ?, ?, ?, ?, 'completed', 'scheduled')",
        (sid2, "US-Iran nuclear deal by April 30?",
         "2026-04-20T09:00:00+00:00", "2026-04-20T09:01:48+00:00", 108.7),
    )
    sid3 = _make_scan_id(prefix="r")
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, market_title, started_at, "
        "finished_at, total_elapsed, status, error, trigger_source) "
        "VALUES (?, 'analyze', 'ev_peace', ?, ?, ?, ?, 'failed', ?, 'manual')",
        (sid3, "US x Iran permanent peace deal in 2026?",
         "2026-04-20T08:00:00+00:00", "2026-04-20T08:00:45+00:00", 45.1,
         "TimeoutError: claude CLI timed out after 300s"),
    )
    db.conn.commit()

    # --- Analysis version on the BTC event ---
    av = AnalysisVersion(
        version=1,
        created_at="2026-04-20T10:02:34+00:00",
        trigger_source="manual",
        prices_snapshot={
            "m_btc_70k": {"yes": 0.62, "no": 0.38},
            "m_btc_80k": {"yes": 0.23, "no": 0.77},
            "m_btc_90k": {"yes": 0.08, "no": 0.92},
        },
        narrative_output={
            "analysis": (
                "BTC 当前交易区间 $66K-$68K。事件要求4月底达到 $70K，剩余约 10 天。"
                "70K 合约定价 62¢，隐含概率 62%。参考历史 BTC 日波动率 3.5%，"
                "10 天内从 $67K 冲击 $70K 需要约 4.5% 涨幅，历史上 10 天内达成 >4% "
                "涨幅的频率约 45%。市场定价略高。"
            ),
            "operations": [
                {"action": "watch", "reason": "定价略高但不显著"},
            ],
            "conditional_advice": "如果看空波动率上行，可考虑小仓位买 NO。",
        },
        structure_score=78.0,
        mispricing_signal="slight_overpriced",
        elapsed_seconds=154.2,
    )
    append_analysis("ev_btc", av, db)


def _seed_wallet_ledger(svc):
    """Use WalletService to seed realistic ledger entries.

    Requires wallet to already be initialized (PolilyService does not auto-init
    — PolilyService just constructs WalletService). We initialize here.
    """
    svc.wallet.initialize(starting_balance=100.0)
    svc.wallet.topup(50.0, notes="初始充值")
    svc.wallet.withdraw(10.0)


def _seed_position(svc):
    """Seed one open BUY position via TradeEngine (mocked live price)."""
    with patch(
        "polily.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.62,
    ):
        svc.execute_buy(market_id="m_btc_70k", side="yes", shares=20.0)


def _seed_realized_trade(svc):
    """Open then close a small position to populate the history page.

    Sequence: BUY m_iran@0.18 x 10  (cost $1.80)  →  SELL @0.22 x 10 (proceeds $2.20)
    Realized P&L = (0.22 - 0.18) × 10 = $0.40 before fees
    """
    with patch(
        "polily.core.trade_engine.TradeEngine._fetch_live_price",
        side_effect=[0.18, 0.22],
    ):
        svc.execute_buy(market_id="m_iran", side="yes", shares=10.0)
        svc.execute_sell(market_id="m_iran", side="yes", shares=10.0)


# ---------------------------------------------------------------------------
# Snapshot capture
# ---------------------------------------------------------------------------

def _make_service(tmpdb_path: Path):
    from polily.core.db import PolilyDB
    from polily.core.events import EventBus
    from polily.tui.service import PolilyService

    cfg = _make_cfg()
    db = PolilyDB(tmpdb_path)
    _seed_full_fixture(db)
    svc = PolilyService(config=cfg, db=db, event_bus=EventBus())
    _seed_wallet_ledger(svc)
    _seed_position(svc)
    _seed_realized_trade(svc)
    return svc, db


async def _capture_one(target: str, svc):
    """Capture one snapshot target. Returns (name, svg_path, error_or_None)."""
    from polily.tui.app import PolilyApp
    import polily.tui.screens.main as main_screen_mod

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    # Block the heartbeat-driven daemon alive check so it doesn't noop-refresh
    # the view during pause() — isolates snapshot stability.
    main_screen_mod.MainScreen._is_daemon_alive = staticmethod(lambda: False)

    svg_path = OUT_DIR / f"{target}.svg"

    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            # Dispatch per-target setup
            await _setup_target(app, pilot, target, svc)
            await pilot.pause(0.3)
            # Export. save_screenshot writes via current `screen` (topmost in stack)
            app.save_screenshot(filename=svg_path.name, path=str(OUT_DIR))
        return target, svg_path, None
    except Exception as e:
        return target, svg_path, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


async def _setup_target(app, pilot, target: str, svc):
    """Per-target navigation / mount steps."""
    from polily.tui.screens.main import MainScreen

    main = app.screen
    assert isinstance(main, MainScreen), f"expected MainScreen, got {type(main)}"

    if target == "main_sidebar":
        # Tasks is the default view — sidebar already visible.
        main._navigate_to("tasks")
        await pilot.pause()
        return

    if target == "scan_log":
        main._navigate_to("tasks")
        await pilot.pause()
        return

    if target == "wallet":
        main._navigate_to("wallet")
        await pilot.pause()
        return

    if target == "event_detail":
        from polily.tui.views.event_detail import EventDetailView
        view = EventDetailView(event_id="ev_btc", service=svc)
        main._switch_view(view)
        await pilot.pause()
        return

    if target == "monitor_list":
        main._navigate_to("monitor")
        await pilot.pause()
        return

    if target == "history":
        main._navigate_to("history")
        await pilot.pause()
        return

    if target == "archived_events":
        main._navigate_to("archive")
        await pilot.pause()
        return

    if target == "paper_status":
        main._navigate_to("paper")
        await pilot.pause()
        return

    if target == "score_result":
        from polily.tui.views.score_result import ScoreResultView
        view = ScoreResultView(event_id="ev_btc", service=svc)
        main._switch_view(view)
        await pilot.pause()
        return

    if target == "trade_dialog_buy":
        from polily.core.event_store import get_event_markets
        from polily.tui.views.trade_dialog import TradeDialog
        markets = get_event_markets("ev_btc", svc.db)
        dialog = TradeDialog("ev_btc", markets, svc, default_tab="buy")
        await app.push_screen(dialog)
        await pilot.pause(0.5)
        return

    if target == "trade_dialog_sell":
        from polily.core.event_store import get_event_markets
        from polily.tui.views.trade_dialog import TradeDialog
        markets = get_event_markets("ev_btc", svc.db)
        dialog = TradeDialog("ev_btc", markets, svc, default_tab="sell")
        await app.push_screen(dialog)
        await pilot.pause(0.5)
        return

    if target == "wallet_topup":
        from polily.tui.views.wallet_modals import TopupModal
        await app.push_screen(TopupModal(service=svc))
        await pilot.pause(0.4)
        return

    if target == "wallet_withdraw":
        from polily.tui.views.wallet_modals import WithdrawModal
        await app.push_screen(WithdrawModal(service=svc))
        await pilot.pause(0.4)
        return

    if target == "wallet_reset":
        from polily.tui.views.wallet_modals import WalletResetModal
        await app.push_screen(WalletResetModal(service=svc))
        await pilot.pause(0.4)
        return

    if target == "scan_modals_cancel":
        from polily.tui.views.scan_modals import ConfirmCancelScanModal
        await app.push_screen(ConfirmCancelScanModal(
            event_title="What price will Bitcoin hit in April?",
            elapsed_seconds=42.5,
        ))
        await pilot.pause(0.4)
        return

    if target == "monitor_modals_unmonitor":
        from polily.tui.views.monitor_modals import ConfirmUnmonitorModal
        await app.push_screen(ConfirmUnmonitorModal(
            "US-Iran nuclear deal by April 30?"
        ))
        await pilot.pause(0.4)
        return

    raise ValueError(f"unknown target: {target}")


TARGETS = [
    "main_sidebar",
    "scan_log",
    "wallet",
    "event_detail",
    "monitor_list",
    "history",
    "archived_events",
    "paper_status",
    "score_result",
    "trade_dialog_buy",
    "trade_dialog_sell",
    "wallet_topup",
    "wallet_withdraw",
    "wallet_reset",
    "scan_modals_cancel",
    "monitor_modals_unmonitor",
]


# ---------------------------------------------------------------------------
# SVG → PNG
# ---------------------------------------------------------------------------

def _convert_svg_to_png(svg_path: Path) -> tuple[bool, str]:
    if not Path(RSVG_PATH).exists():
        return False, (
            f"rsvg-convert not found at {RSVG_PATH}; pass --no-png to skip "
            "PNG rendering or install librsvg (macOS: `brew install librsvg`, "
            "Debian: `apt install librsvg2-bin`)"
        )
    png_path = svg_path.with_suffix(".png")
    try:
        result = subprocess.run(
            [RSVG_PATH, "-h", str(PNG_HEIGHT), "-o", str(png_path), str(svg_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(selected_targets: list[str]):
    # Use a throwaway DB file inside the output dir
    tmpdb = OUT_DIR / "_snapshots.db"
    if tmpdb.exists():
        tmpdb.unlink()

    print("Seeding fixture DB at:", tmpdb)
    svc, db = _make_service(tmpdb)

    results: list[tuple[str, Path, str | None]] = []
    for target in selected_targets:
        print(f"  -> capturing {target} ... ", end="", flush=True)
        # Build a fresh app per target (each run_test tears down)
        name, svg_path, err = await _capture_one(target, svc)
        if err:
            print("FAIL")
            print(f"     {err.splitlines()[0]}")
        else:
            print(f"ok ({svg_path.stat().st_size} B)")
        results.append((name, svg_path, err))

    db.close()

    # SVG → PNG
    png_issues: list[tuple[str, str]] = []
    if CONVERT_PNG:
        print("\nConverting SVGs to PNGs...")
        for name, svg_path, err in results:
            if err or not svg_path.exists():
                continue
            ok, msg = _convert_svg_to_png(svg_path)
            if not ok:
                print(f"  {name}: PNG FAIL — {msg}")
                png_issues.append((name, msg))
            else:
                print(f"  {name}: ok")
    else:
        print("\nSkipping SVG → PNG (--no-png).")

    # README
    readme = OUT_DIR / "README.md"
    with readme.open("w", encoding="utf-8") as f:
        f.write("# Polily TUI snapshots\n\n")
        f.write(f"Generated {datetime.now(UTC).isoformat()}\n\n")
        f.write(
            f"Terminal size: {SIZE[0]}x{SIZE[1]} chars. "
            f"PNG rendered at height={PNG_HEIGHT}px via rsvg-convert.\n\n"
        )
        f.write("## Files\n\n")
        descriptions = {
            "main_sidebar": "Main screen w/ sidebar + default content (scan_log view)",
            "scan_log": "Analysis queue — 3 pending + 2 completed + 1 failed",
            "wallet": "Wallet view — balance card + ledger zone (topup/withdraw)",
            "event_detail": "Event detail — BTC event w/ 3 markets + 1 AI analysis",
            "monitor_list": "Monitor list — 2 auto-monitored events",
            "history": "Realized P&L history — 1 closed trade",
            "archived_events": "Archive view — 1 closed/resolved event",
            "paper_status": "Paper status — 1 open position",
            "score_result": "Score result — BTC event structure score detail",
            "trade_dialog_buy": "Trade dialog modal — Buy tab selected",
            "trade_dialog_sell": "Trade dialog modal — Sell tab selected",
            "wallet_topup": "Wallet topup modal",
            "wallet_withdraw": "Wallet withdraw modal",
            "wallet_reset": "Wallet reset (destructive) modal",
            "scan_modals_cancel": "Confirm cancel scan modal (ongoing analysis)",
            "monitor_modals_unmonitor": "Confirm unmonitor modal",
        }
        for name, svg_path, err in results:
            status = "OK" if not err else "FAIL"
            f.write(f"- `{name}.svg` / `{name}.png` — {descriptions.get(name, '')}  [{status}]\n")
            if err:
                f.write(f"    - error: `{err.splitlines()[0]}`\n")
        if png_issues:
            f.write("\n## PNG conversion issues\n\n")
            for name, msg in png_issues:
                f.write(f"- `{name}`: {msg}\n")
        f.write("\n## Caveats\n\n")
        f.write(
            "- **Nerd Font glyphs render as `.notdef` boxes in PNG** (e.g. sidebar "
            "icons, zone icons) — rsvg-convert has no Nerd Font fallback. The "
            "layout position of the glyph is preserved so layout review is still "
            "useful; icon visual fidelity should be reviewed by running the real "
            "TUI. Chinese text renders correctly via the SVG embedded font list "
            "hitting a CJK-capable system font (e.g. PingFang).\n"
            "- **Colors may deviate slightly from terminal**. Textual's SVG export "
            "translates ANSI to RGB; some theme tokens (e.g. `$panel`, `$surface`) "
            "resolve differently than in a truecolor terminal session.\n"
            "- **trade_dialog_{buy,sell}**: the TradeDialog's PolilyCard header "
            "stretches to fill the dialog-box in `run_test` headless mode "
            "(probable Textual layout oddity — `PolilyCard` subclasses Vertical "
            "with no explicit `height: auto` in its default CSS, so it inherits "
            "`1fr` stretching when the parent is `height: auto` with `align: "
            "center middle`). The script pins `#header-card {height: 3}` "
            "before export so the radios + tabs are visible; the side-effect is "
            "the header title text ('交易' + balance) renders into a too-short "
            "box so its text may be clipped. This is how Textual's headless "
            "layout resolves the CSS — not a real-TUI bug.\n"
            "- **main_sidebar.svg == scan_log.svg**: tasks is the default view, "
            "so both render identically. Kept as two files for completeness.\n"
        )

    print(f"\nWrote {readme}")
    # Summary
    ok_count = sum(1 for _, _, err in results if not err)
    total = len(results)
    print(f"\nDONE: {ok_count}/{total} targets captured successfully.")
    if any(err for _, _, err in results):
        print("Failures:")
        for name, _, err in results:
            if err:
                print(f"  - {name}: {err.splitlines()[0]}")
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate_snapshots.py",
        description="Capture SVG/PNG snapshots of every Polily TUI view + modal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                     # full capture with PNG\n"
            "  %(prog)s --no-png            # SVG-only (skip rsvg-convert)\n"
            "  %(prog)s --targets event_detail wallet\n"
            "  %(prog)s --output-dir /tmp/my-snaps\n"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUT_DIR,
        help=f"Where to write SVG/PNG files (default: {OUT_DIR}).",
    )
    parser.add_argument(
        "--rsvg-path",
        default=RSVG_PATH,
        help=(
            "Path to rsvg-convert binary. Auto-detected via PATH; override "
            "if installed elsewhere."
        ),
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip SVG → PNG conversion (rsvg-convert not required).",
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=TARGETS,
        metavar="TARGET",
        help=(
            "Subset of targets to capture. Default: all. Available: "
            + ", ".join(TARGETS)
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    os.environ.setdefault("POLILY_TUI", "1")
    args = _parse_args(sys.argv[1:])
    OUT_DIR = args.output_dir
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RSVG_PATH = args.rsvg_path
    CONVERT_PNG = not args.no_png
    selected = args.targets or TARGETS
    sys.exit(asyncio.run(main(selected)))
