"""First-run onboarding: welcome message and paper trading recommendation."""

from pathlib import Path

WELCOME_TEXT = """\
[bold]WELCOME TO POLILY — Your Polymarket Decision Copilot[/bold]

Finds the best market opportunity each day. Shows direction lean, sizes your risk.

[bold]GETTING STARTED[/bold]
  1. Run [cyan]polily[/cyan] — 打开交互式界面，按 s 开始扫描
  2. 或 [cyan]polily scan[/cyan] — CLI 模式扫描
  3. Got a view? Try [cyan]polily match "BTC will hit 70k"[/cyan]
  4. Like a market? Paper trade first: [cyan]polily mark --rank 1 --side yes[/cyan]
  5. Track results: [cyan]polily paper-report[/cyan]
  6. When paper PnL is positive → start small real trades ($5-10)

[bold]TIP[/bold]: Your first trade is always paper (simulated). Build a track record before risking real money.

[bold]KEY COMMANDS[/bold]
  polily                   交互式终端界面（推荐）
  polily scan              CLI 扫描
  polily scan --simple     新手模式（中文）
  polily match "..."       观点匹配
  polily daily             每日简报 + 自动结算
  polily export trades     导出 CSV
  polily paper-report      绩效 + 毕业评估

[bold]TUI SHORTCUTS[/bold]
  s     开始扫描          0     任务记录
  1/2/3 研究/观察/持仓    a     AI 深度分析
  y/n   买YES/NO          o     打开链接
  < >   切换分析版本      q     退出
"""


def should_show_onboarding(marker_path: Path) -> bool:
    return not marker_path.exists()


def mark_onboarding_done(marker_path: Path):
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.touch()
