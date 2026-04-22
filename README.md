# Polily — A Polymarket Monitoring Agent That Actually Works

Paste a Polymarket event URL and Polily decides **whether it's worth your time, scores the structure, hunts mispricing, watches for moves, and closes out positions automatically when markets resolve**. A monitoring agent built for small accounts.

## Why You Need It

Polymarket is unfriendly to small accounts:

- **Spread and thin liquidity quietly eat your PnL** — if you don't price them in before clicking, you're already behind
- **A good story doesn't make a good market** — narratives are seductive; structure is what the numbers say
- **Watching markets is expensive** — refreshing pages by hand doesn't scale past two or three events

## Who It's For

- Wallet of $50–$500 — can't afford to be the exit liquidity
- Has an edge in at least one of crypto / macro / tech, and **finds events on their own**
- Willing to spend 5–10 minutes a day following a few events, but won't watch them by hand

> For events you bring in, Polily judges whether they're worth your money and time. Once added to monitoring, it watches the price, runs mispricing checks, and surfaces meaningful moves.

## What It Does For You

1. **Paste a URL → instant dossier + value check** — pulls the full event + child markets, scores 0–100 across spread / depth / objectivity / time / friction, surfaces hidden costs, and tells you whether the event is worth following
2. **Mispricing detection** — for crypto threshold markets, compares against a log-normal vol model fed by live Binance data and flags probabilities that look mis-priced
3. **Background watching + move alerts** — a daemon polls prices for everything in your watchlist; meaningful moves trigger AI analysis and notifications
4. **Paper trading with a full wallet** — real cash balance, aggregated positions (YES + NO coexist), Polymarket-accurate taker fees, buy / add / reduce / close, and automatic settlement when markets resolve — so your paper PnL curve reflects what real trading would have looked like

> A high structure score ≠ YES will win. It measures *whether the market is tradeable*, not *whether you should buy* — keep the two separate.

## What's new in v0.8.0

Full visual rework — consistent atom-based widgets, Chinese status labels, a Polily brand theme, EventBus-driven reactive views with zero manual refresh, uniform footer keybindings, an optional phosphor-green `polily-geek` theme, and an in-app changelog viewer (`6` key). **Nerd Font required** — see Requirements below. Full list in [CHANGELOG](CHANGELOG.md) or press `6` inside the TUI.

## Quick Start

```bash
git clone https://github.com/ShiyuCheng2018/polily.git && cd polily
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

polily   # launches the TUI; everything happens inside it
```

In the TUI, paste a Polymarket event URL (looks like `https://polymarket.com/event/...`) into the **Tasks** pane. Polily fetches and scores it; from there you can add it to monitoring or open a paper trade.

## Requirements

Polily v0.8.0+ requires a [Nerd Font](https://www.nerdfonts.com/) installed
and configured as your terminal font. The TUI uses Nerd Font glyphs for
status icons, action markers, and domain entities (event / market / wallet).

### macOS (Homebrew)

```bash
brew install --cask font-jetbrains-mono-nerd-font
```

Then set your terminal's font to `JetBrainsMono Nerd Font`:

- **Ghostty**: edit `~/Library/Application Support/com.mitchellh.ghostty/config` and set `font-family = "JetBrainsMono Nerd Font"` (reload with `Cmd+Shift+,`)
- **iTerm2**: Preferences → Profiles → Text → Font → `JetBrainsMono Nerd Font`
- **Terminal.app**: Preferences → Profiles → Font → Change → `JetBrainsMono Nerd Font`

Any Nerd Font works (`font-fira-code-nerd-font`, `font-hack-nerd-font`,
`font-meslo-lg-nerd-font`). Polily tests on JetBrainsMono NF but glyph
positions are the same across all NF fonts.

### Verify

```bash
polily doctor
```

The "Nerd Font 字体" section prints sample glyphs. If you see `□` tofu
boxes, the font is not yet active — check your terminal's font setting.

Minimum terminal size: **100×30 cells**. Polily works at smaller sizes but
column layout may wrap. 120×30 or larger recommended.

### Python & Claude CLI

- Python 3.11+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (optional, used for AI analysis): `npm install -g @anthropic-ai/claude-code && claude login`
- Without Claude CLI, Polily still runs — AI components fall back to rule-based mode

## TUI Shortcuts

| Key | Action |
|-----|--------|
| `0` | Tasks log |
| `1` | Watchlist |
| `2` | Paper positions |
| `3` | Wallet (balance + ledger + topup/withdraw) |
| `4` | History |
| `5` | Archive |
| `6` | Changelog |
| `r` | Refresh current page |
| `o` | Open Polymarket link (detail pages) |
| `↑ / ↓` | Navigate menu |
| `q` | Quit |

Inside the Wallet page: `t` topup · `w` withdraw · `shift+r` reset (or click `重置钱包`).
Inside an event detail page: `a` AI analysis · `t` trade · `m` toggle monitoring · `v` switch analysis version.

See [docs/ui-guide.md](docs/ui-guide.md) for the full v0.8.0 interaction reference.

## Background Scheduler

Price polling, movement detection, and AI analysis run inside a daemon:

```bash
polily scheduler run        # foreground (typically launched by launchd)
polily scheduler status     # status
polily scheduler restart    # restart
polily scheduler stop       # stop
polily reset                # wipe DB / logs for a clean restart
polily reset --wallet-only  # reset wallet only, keep events/markets/analyses
```

## Current Limitations

- Mispricing detection currently only covers crypto threshold markets
- AI analysis requires Claude CLI; otherwise it falls back to rule-based mode
- Data comes from Polymarket public APIs — real-time freshness is bounded by them

## Development

```bash
pytest tests/ -q              # ~900 tests
ruff check polily/ tests/    # lint
pyright polily/              # type check
```

See [docs/architecture.md](docs/architecture.md) for design details and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

MIT
