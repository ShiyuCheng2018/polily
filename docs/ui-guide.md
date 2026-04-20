# Polily UI Guide

> User-facing reference for Polily TUI v0.8.0+.

## Terminal requirements

- **Minimum size:** 100×30 cells (hard floor — below this, layouts wrap or
  truncate).
- **Recommended:** 120×30 or larger.
- **Nerd Font required.** The TUI renders Nerd Font Awesome Legacy glyphs
  (U+F000 range) throughout. Without a Nerd Font installed and selected
  in your terminal, you will see `□` tofu boxes instead of icons.

Run `polily doctor` to check terminal size, font rendering, DB health,
and `claude` CLI availability in one shot.

## Theme

Polily ships with `polily-dark` as the default theme. You can switch to
any Textual built-in theme at runtime:

1. Press `Ctrl+P` to open the command palette.
2. Type `theme` to filter.
3. Select from: `polily-dark`, `textual-dark`, `textual-light`, `nord`,
   `dracula`, `gruvbox`, `tokyo-night`, `solarized-light`, `monokai`,
   `catppuccin-mocha`, `catppuccin-latte`, `flexoki`.
4. The selection persists only for the current session. Restart Polily
   to reset to `polily-dark`.

## Key bindings

### Global (all views)

| Key | Action |
|-----|--------|
| `q` | 退出 |
| `?` | 帮助 |
| `Esc` | 返回上一级 |
| `Ctrl+P` | 命令面板 / 主题切换 |

### Navigation (list views — scan_log / monitor_list / market_list / history / archived_events)

| Key | Action |
|-----|--------|
| `j` / `↓` | 下 |
| `k` / `↑` | 上 |
| `g` | 顶部 |
| `Shift+G` | 底部 |
| `Enter` | 打开详情 |
| `r` | 手动刷新（通常不需要 — 视图通过 EventBus 自动更新） |
| `/` | 搜索（仅部分视图） |

### CRUD (where supported)

| Key | Action |
|-----|--------|
| `n` | 新建 |
| `e` | 编辑 |
| `d` | 删除（始终经由确认弹窗） |
| `Enter` | 打开 |

**Destructive ops convention:** Polily never destroys state on a single
keystroke. All delete / cancel / reset actions go through a confirm
modal.

### View-specific

每个视图底部状态栏会显示可用的快捷键。常见示例:

- **scan_log:** `c` 取消运行中的分析
- **wallet:** `t` 充值 / `w` 提现 / `r` 重置（重置要求输入 `RESET` 二次确认）
- **market_detail:** `a` AI 分析 / `t` 交易 / `m` 监控切换 / `v` 版本历史 / `o` 打开 Polymarket 链接 / `r` 刷新

### Modals

| Key | Action |
|-----|--------|
| `Enter` | 确认 |
| `Esc` | 取消 |
| `Tab` | 切换 Buy/Sell（trade_dialog） |

Destructive modals (reset / bulk close) require typing a keyword such as
`RESET` before the confirm button becomes active — prevents accidental
data loss.

## Icon glossary

All icons are Nerd Font Awesome Legacy codepoints (U+F000 range),
defined in `scanner/tui/icons.py`. They render correctly only in a
terminal configured to use a Nerd Font.

| 语义 | 码点 | Font Awesome 名称 |
|------|------|-------------------|
| 事件 | U+F073 | fa-calendar |
| 市场 | U+F080 | fa-bar-chart-o |
| 钱包 | U+F0D6 | fa-money |
| 持仓 | U+F0B1 | fa-briefcase |
| 分析 / 扫描 | U+F002 | fa-search |
| 待执行 | U+F017 | fa-clock-o |
| 运行中 | U+F021 | fa-refresh |
| 已完成 | U+F00C | fa-check |
| 失败 | U+F00D | fa-times |
| 已取消 | U+F05E | fa-ban |
| 已覆盖 | U+F079 | fa-retweet |
| 自动监控开启 | U+F06E | fa-eye |
| 通知 | U+F0F3 | fa-bell |
| 买入 | U+F067 | fa-plus |
| 卖出 | U+F068 | fa-minus |
| 设置 | U+F085 | fa-cogs |

Run `polily doctor` to print a sample line of these glyphs — the fastest
way to visually confirm your terminal is using a Nerd Font.

## Status 名词

### scan_logs.status

| English (internal code) | 中文显示 |
|-------------------------|----------|
| pending | 待执行 |
| running | 运行中 |
| completed | 已完成 |
| failed | 失败 |
| cancelled | 已取消 |
| superseded | 已覆盖 |

### scan_logs.trigger_source

| English (internal code) | 中文显示 |
|-------------------------|----------|
| manual | 手动 |
| scheduled | 定时 |
| movement | 异动 |
| scan | 批量 |

Translation source: `scanner/tui/i18n.py`. Unknown enum values pass
through untranslated.

## Exempt terms (industry / domain canon, NOT translated)

These stay in English everywhere — translating them would be wrong, not
helpful:

- `YES` / `NO` — Polymarket outcome sides
- `bid` / `ask` — orderbook canon
- `CLOB` / `negRisk` — Polymarket protocol terms
- `API` / `URL` / `ID` — technical identifiers
- `P&L` / `ROI` — financial canon
- `$` / `%` / `USD` — units

## Developer notes

### EventBus is in-process

The `scanner.core.events.EventBus` singleton introduced in v0.8.0 is
**process-local**. When the TUI process mutates state (user clicks a
button, submits a trade, cancels a scan), bus events propagate to
subscribed views within the same process — driving reactive updates
without manual refresh.

**Cross-process updates still require DB polling.** The scheduler
daemon runs in a separate process (launchd-started), writes to
`data/polily.db`, and CANNOT publish to the TUI's EventBus. Views that
need to reflect daemon-driven changes (scan_log after a scheduled
analysis completes, price updates from the poll job) still depend on
periodic DB re-reads or the TUI restarting the daemon on launch. v0.8.0
does not solve this; it's documented as a known gap for v0.9.0
consideration.

### Bus callback threading convention

View handlers subscribed to `EventBus` topics MUST wrap UI mutations in
`self.app.call_from_thread(...)`:

```python
def _on_scan_update(self, payload: dict) -> None:
    self.app.call_from_thread(self._render_all)
```

The bus invokes handlers synchronously on the publishing thread. Even
when the publisher is the UI thread (user action), `call_from_thread`
is still the right pattern — it's a no-op when already on the UI
thread, and prevents silent crashes if the publisher moves to a non-UI
thread later.

### Mount-once refresh pattern

Textual's `child.remove()` is deferred. If you re-mount a widget with
the same `id` on the same tick, `DuplicateIds` will fire. The correct
pattern is to mount the widget once in `on_mount()`, then refresh it in
place via `table.clear()` + `add_row()` (or the equivalent for your
widget type).

## Troubleshooting

### I see `□` tofu boxes everywhere

Your terminal is not using a Nerd Font. Run `polily doctor` for install
instructions. Quick fix on macOS:

```bash
brew install --cask font-jetbrains-mono-nerd-font
```

Then set your terminal's font to `JetBrainsMono Nerd Font`:

- **Ghostty:** edit `~/Library/Application Support/com.mitchellh.ghostty/config`,
  set `font-family = "JetBrainsMono Nerd Font"`, reload with `Cmd+Shift+,`.
- **iTerm2:** Preferences → Profiles → Text → Font → `JetBrainsMono Nerd Font`.

Other Nerd Font options: `font-fira-code-nerd-font`, `font-hack-nerd-font`,
`font-meslo-lg-nerd-font`.

### Theme colors look wrong

`Ctrl+P → Change Theme` shows the current theme. If it's not
`polily-dark`, switch back. Restarting Polily also restores the default.

### Layout wraps / text truncated

Terminal too narrow. Enlarge to at least 100×30 (recommended 120×30).
`polily doctor` reports the current size and flags if it's below the
minimum.

### Event detail panel covered other zones

Fixed during v0.8.0 beta in commit `47454a5` (bounded `VerticalScroll`
height in `market_detail`). If you still see this on v0.8.0+, file an
issue.
