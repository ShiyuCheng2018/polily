"""PortfolioView: open positions with realtime P&L from Polymarket API."""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.pnl import calc_unrealized_pnl
from scanner.tui.service import ScanService

logger = logging.getLogger(__name__)


class PaperStatusView(Widget):
    """Portfolio view with realtime price updates and P&L calculation."""

    DEFAULT_CSS = """
    PaperStatusView { height: 1fr; }
    PaperStatusView #portfolio-title { padding: 1 0 0 0; text-style: bold; }
    PaperStatusView #portfolio-summary { padding: 0 0 1 2; color: $text-muted; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._trades = []
        self._http: httpx.AsyncClient | None = None
        self._fetching = False
        self._last_update = 0.0
        self._prices: dict[str, float] = {}  # market_id → YES price

    def compose(self) -> ComposeResult:
        yield Static(" 持仓", id="portfolio-title")
        yield Static("", id="portfolio-summary")
        yield DataTable(id="portfolio-table")

    def on_mount(self) -> None:
        self._trades = self.service.get_paper_trades()

        table = self.query_one("#portfolio-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("市场", "方向", "现价", "价值", "份数", "入场/结算")

        if not self._trades:
            self.query_one("#portfolio-summary", Static).update(
                " [dim]暂无持仓。在市场详情页按 y/n 标记 paper trade。[/dim]"
            )
        else:
            # Initial fill with entry prices (before first API fetch)
            self._fill_table_initial()
            # Start realtime timer
            self.set_interval(5, self._tick)
            # Immediately fetch once
            self._tick()

    def on_unmount(self) -> None:
        # httpx client is created/used in worker thread's event loop,
        # cannot safely close from main thread. Set to None so next
        # _async_fetch creates a fresh one if widget is remounted.
        self._http = None

    def _fill_table_initial(self) -> None:
        """Fill table with entry prices before first API fetch."""
        table = self.query_one("#portfolio-table", DataTable)
        for t in self._trades:
            entry_time = self._format_entry_time(t.marked_at)
            countdown = self._get_countdown(t.market_id)
            shares = f"{t.position_size_usd / t.entry_price:.0f}" if t.entry_price > 0 else "?"
            table.add_row(
                t.title[:30],
                t.side.upper(),
                f"${t.entry_price:.2f} ...",
                f"${t.position_size_usd:.2f} ...",
                shares,
                f"{entry_time} {countdown}",
                key=t.id,
            )

    def _tick(self) -> None:
        """Timer tick — fetch prices in background worker."""
        if self._fetching or not self._trades:
            return
        self.run_worker(self._async_fetch, thread=True, exclusive=True)

    async def _async_fetch(self) -> None:
        """Concurrent price fetch for all open trades."""
        self._fetching = True
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
                self._http = client  # for _fetch_one to use
                market_ids = list({t.market_id for t in self._trades})
                tasks = [self._fetch_one(mid) for mid in market_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                prices = {}
                for mid, result in zip(market_ids, results, strict=True):
                    if isinstance(result, float):
                        prices[mid] = result
                self._prices.update(prices)
                self._last_update = time.monotonic()
                self.app.call_from_thread(self._update_table)
        except Exception:
            logger.debug("Portfolio price fetch failed", exc_info=True)
        finally:
            self._http = None
            self._fetching = False

    async def _fetch_one(self, market_id: str) -> float:
        """Fetch single market YES price from Gamma API."""
        if not self._http:
            raise ValueError("No HTTP client")
        resp = await self._http.get(
            f"https://gamma-api.polymarket.com/markets/{market_id}",
        )
        if resp.status_code == 200:
            data = resp.json()
            prices_raw = data.get("outcomePrices", "[]")
            parsed = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if parsed:
                return float(parsed[0])
        raise ValueError(f"No price for {market_id}")

    def _update_table(self) -> None:
        """Refresh table rows and summary with latest prices."""
        try:
            table = self.query_one("#portfolio-table", DataTable)
        except Exception:
            return

        total_value = 0.0
        total_pnl = 0.0
        total_cost = 0.0

        import contextlib

        from textual.coordinate import Coordinate

        for t in self._trades:
            yes_price = self._prices.get(t.market_id)

            # Fallback chain: API → scan snapshot → entry price
            is_snapshot = False
            if yes_price is None:
                yes_price = self._get_scan_price(t.market_id)
                is_snapshot = True
            if yes_price is None:
                yes_price = t.entry_price if t.side == "yes" else (1 - t.entry_price)
                is_snapshot = True

            pnl_data = calc_unrealized_pnl(t.side, t.entry_price, yes_price, t.position_size_usd)

            # Current price (side-aware) + change %
            cur = yes_price if t.side == "yes" else round(1 - yes_price, 3)
            change_pct = pnl_data["pnl_pct"]
            snap = " 快照" if is_snapshot else ""
            if change_pct > 0:
                price_str = f"${cur:.2f} (+{change_pct:.1f}%){snap}"
            elif change_pct < 0:
                price_str = f"${cur:.2f} ({change_pct:.1f}%){snap}"
            else:
                price_str = f"${cur:.2f}{snap}"

            # Value + P&L $ + P&L %
            pnl_val = pnl_data["pnl"]
            value = pnl_data["current_value"]
            if pnl_val > 0:
                value_str = f"${value:.2f} (+${pnl_val:.2f} +{change_pct:.1f}%)"
            elif pnl_val < 0:
                value_str = f"${value:.2f} (-${abs(pnl_val):.2f} {change_pct:.1f}%)"
            else:
                value_str = f"${value:.2f}"

            entry_time = self._format_entry_time(t.marked_at)
            countdown = self._get_countdown(t.market_id)

            # Update row — columns: 市场(0) 方向(1) 现价(2) 价值(3) 份数(4) 入场/结算(5)
            with contextlib.suppress(Exception):
                row_idx = table.get_row_index(t.id)
                table.update_cell_at(Coordinate(row_idx, 2), price_str)
                table.update_cell_at(Coordinate(row_idx, 3), value_str)
                table.update_cell_at(Coordinate(row_idx, 4), f"{pnl_data['shares']:.0f}")
                table.update_cell_at(Coordinate(row_idx, 5), f"{entry_time} {countdown}")

            total_value += value
            total_pnl += pnl_val
            total_cost += t.position_size_usd

        # Summary bar
        pnl_pct_total = total_pnl / total_cost * 100 if total_cost > 0 else 0
        if total_pnl >= 0:
            pnl_color = "green"
        else:
            pnl_color = "red"

        elapsed = time.monotonic() - self._last_update if self._last_update > 0 else 0
        update_str = f"{elapsed:.0f}s前" if elapsed > 0 else "..."

        import contextlib
        with contextlib.suppress(Exception):
            self.query_one("#portfolio-summary", Static).update(
                f" 总计: {len(self._trades)} | "
                f"持仓价值: ${total_value:.2f} | "
                f"浮动盈亏: [{pnl_color}]{'+' if total_pnl >= 0 else ''}"
                f"${total_pnl:.2f} ({pnl_pct_total:+.1f}%)[/{pnl_color}] | "
                f"[dim]更新: {update_str}[/dim]"
            )

    def _get_scan_price(self, market_id: str) -> float | None:
        """Fallback: get YES price from scan data."""
        candidates = self.service.get_all_candidates()
        for c in candidates:
            if c.market.market_id == market_id:
                return c.market.yes_price
        return None

    def _get_countdown(self, market_id: str) -> str:
        """Get settlement countdown from market_states."""
        from scanner.market_state import get_market_state
        from scanner.tui.utils import format_countdown

        state = get_market_state(market_id, self.service.db)
        if state and state.resolution_time:
            return format_countdown(state.resolution_time)
        return "?"

    def _format_entry_time(self, marked_at: str) -> str:
        """Format entry time as 'MM-DD (Xd)'."""
        try:
            dt = datetime.fromisoformat(marked_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            days = (datetime.now(UTC) - dt).total_seconds() / 86400
            return f"{dt.strftime('%m-%d')} ({days:.0f}天)"
        except (ValueError, TypeError):
            return "?"
