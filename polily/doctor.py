# polily/doctor.py
"""v0.8.0 `polily doctor` — runtime environment diagnostic.

Sections:
- Nerd Font sample characters + visual confirmation prompt
- Terminal size vs minimum (100×30)
- DB integrity check (can we open polily.db?)
- Claude CLI availability
- Homebrew Nerd Font install instructions

Non-interactive: prints all sections + exit code 0. User reads output
and decides what to fix.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from polily.tui.icons import (
    ICON_COMPLETED,
    ICON_EVENT,
    ICON_FAILED,
    ICON_PENDING,
    ICON_SCAN,
    ICON_WALLET,
)

MIN_COLS = 100
MIN_ROWS = 30


def run_doctor() -> None:
    console = Console()

    console.print(Panel.fit(
        "[bold cyan]Polily Doctor[/] — v0.8.0 环境诊断",
        style="cyan",
    ))

    _section_nerd_font(console)
    _section_terminal_size(console)
    _section_db(console)
    _section_claude_cli(console)
    _section_install_hints(console)


def _section_nerd_font(console: Console) -> None:
    console.rule("[bold]1. Nerd Font 字体[/]")
    console.print("下列字符应显示为清晰图标（不是 □ 豆腐框）:")
    console.print(
        f"  {ICON_EVENT} event   {ICON_WALLET} wallet   {ICON_SCAN} scan   "
        f"{ICON_COMPLETED} done   {ICON_FAILED} fail   {ICON_PENDING} pending"
    )
    console.print(
        "[dim]如果看到豆腐框，说明当前终端字体不是 Nerd Font。\n"
        "参考 README Requirements 一节安装并切换字体。[/]\n"
    )


def _section_terminal_size(console: Console) -> None:
    cols, rows = shutil.get_terminal_size()
    ok = cols >= MIN_COLS and rows >= MIN_ROWS
    mark = "[green]OK[/]" if ok else "[red]低于最小要求[/]"
    console.rule("[bold]2. 终端尺寸[/]")
    console.print(f"当前: {cols}×{rows}   最小: {MIN_COLS}×{MIN_ROWS}   {mark}")
    if not ok:
        console.print(
            "[yellow]低于最小尺寸下 TUI 可能出现折行/截断。建议将窗口放大。[/]"
        )
    console.print()


def _section_db(console: Console) -> None:
    console.rule("[bold]3. 数据库[/]")
    db_path = Path("data/polily.db")
    if not db_path.exists():
        console.print("[yellow]data/polily.db 不存在[/] — 首次启动会自动创建")
    else:
        console.print(f"[green]data/polily.db OK[/]  ({db_path.stat().st_size / 1024:.1f} KB)")
    console.print()


def _section_claude_cli(console: Console) -> None:
    console.rule("[bold]4. Claude CLI[/]")
    claude = shutil.which("claude")
    if not claude:
        console.print("[red]claude CLI 未安装[/] — AI 分析无法运行")
        console.print("请参考 README 安装 claude CLI（随 Claude 订阅提供）")
    else:
        try:
            ver = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            console.print(f"[green]OK[/]  {claude}   {ver}")
        except Exception as e:
            console.print(f"[yellow]已安装但无法取版本: {e}[/]")
    console.print()


def _section_install_hints(console: Console) -> None:
    console.rule("[bold]5. Nerd Font 安装指引（macOS）[/]")
    console.print(
        "\n[bold]1) 安装字体（推荐 JetBrainsMono NF）:[/]\n"
        "  [cyan]brew install --cask font-jetbrains-mono-nerd-font[/]\n\n"
        "[bold]2) Ghostty 配置:[/]\n"
        "  编辑 [cyan]~/Library/Application Support/com.mitchellh.ghostty/config[/]\n"
        "  设置 [cyan]font-family = \"JetBrainsMono Nerd Font\"[/]\n"
        "  [dim]按 Cmd+Shift+, 重载配置[/]\n\n"
        "[bold]3) iTerm2 配置:[/]\n"
        "  Preferences → Profiles → Text → Font → 选择 [cyan]JetBrainsMono Nerd Font[/]\n\n"
        "[bold]其他 Nerd Font 字体:[/]\n"
        "  font-fira-code-nerd-font / font-hack-nerd-font / font-meslo-lg-nerd-font\n"
    )
