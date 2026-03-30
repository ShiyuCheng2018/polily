# Polily — Polymarket Decision Copilot

Finds structure, shows direction lean, sizes your risk. You pull the trigger.

Scans 8000+ Polymarket markets, scores tradability, detects crypto mispricing, and provides AI-powered analysis — all in an interactive terminal UI.

## What It Does

- **Scans** 8000+ markets, filters noise, scores structure quality (0-100)
- **Detects** crypto mispricing via log-normal vol model (Binance/ccxt)
- **Analyzes** markets with 5 AI agents (Claude CLI) — narratives, risk flags, research checklists
- **Tracks** paper trades with friction-adjusted PnL and graduation assessment

## What It Does NOT Do

- Give definitive trade signals — shows conditional lean, not "buy this"
- Auto-execute trades
- Replace your judgment

## Quick Start

```bash
git clone https://github.com/ShiyuCheng2018/polily.git && cd polily
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Interactive TUI (recommended)
polily

# CLI scan
polily scan

# Match your view to markets
polily match "BTC will hit 70k"
```

### Requirements

- Python 3.11+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (optional, for AI features): `npm install -g @anthropic-ai/claude-code && claude login`
- Without Claude CLI, everything works in rule-based mode (`--no-ai`)

## TUI Shortcuts

| Key | Action |
|-----|--------|
| `s` | Start scan |
| `0/1/2/3` | Task log / Research / Watchlist / Paper trades |
| `Enter` | Open detail |
| `Esc` | Go back |
| `a` | AI deep analysis (in detail view) |
| `< >` | Switch analysis versions |
| `y/n` | Paper trade YES/NO |
| `o` | Open in browser |
| `q` | Quit |

## CLI Commands

```bash
polily                     # Interactive TUI
polily scan                # CLI scan (--brief, --verbose, --lean, --no-ai)
polily match "..."         # Opinion matching
polily daily               # Daily briefing + auto-resolve
polily backtest            # Directional backtest
polily mark --rank 1 -s yes  # Paper trade
polily paper-report        # Performance + graduation
polily export trades       # Export to CSV
```

## AI Agents

5 agents via `claude -p` CLI (included in Claude subscription, no extra cost):

| Agent | Purpose |
|-------|---------|
| MarketAnalyst | Objectivity scoring, catalyst extraction |
| NarrativeWriter | Analysis narrative, risk flags, research checklist |
| BriefingAnalyst | Daily delta interpretation |
| CrossDomainInsight | Event x market cross-domain analysis |
| ReviewAnalyst | Paper trading performance coaching |

AI is optional. Disable with `polily scan --no-ai` or `ai.enabled: false` in config.

## Limitations

- Mispricing detection only works for crypto threshold markets
- AI quality depends on Claude CLI availability
- TUI exit uses `os._exit(0)` due to Claude CLI subprocess cleanup
- Good market structure ≠ good trade — the copilot sizes risk, you make the call

## Development

```bash
pytest tests/ -q              # 339 tests
ruff check scanner/ tests/    # Lint
pyright scanner/              # Type check
```

See [docs/architecture.md](docs/architecture.md) for detailed design and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

MIT
