from __future__ import annotations

import json as _json

from rich.console import Console

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity, severity_exit_code

_MARK = {
    Severity.OK: "[green]OK[/]",
    Severity.INFO: "[dim]info[/]",
    Severity.WARN: "[yellow]WARN[/]",
    Severity.CRITICAL: "[red]CRITICAL[/]",
    Severity.SKIPPED: "[dim]skipped[/]",
}


def _role(ctx: DoctorContext) -> str:
    if ctx.launchd_label.endswith(".dev"):
        return "dev"
    if ctx.data_dir_tier in ("cli", "env"):
        return "prod"
    return "prod"


def _summary(results: list[CheckResult]) -> dict:
    counts = {s.value: 0 for s in Severity}
    for r in results:
        counts[r.severity.value] += 1
    counts["exit_code"] = severity_exit_code(r.severity for r in results)
    return counts


def render_json(version: str, ctx: DoctorContext, results: list[CheckResult]) -> None:
    payload = {
        "polily_version": version,
        "instance": {
            "role": _role(ctx),
            "data_dir": str(ctx.data_dir),
            "db_path": str(ctx.db_path),
            "launchd_label": ctx.launchd_label,
            "resolution_tier": ctx.data_dir_tier,
        },
        "summary": _summary(results),
        "checks": [r.model_dump(mode="json") for r in results],
    }
    print(_json.dumps(payload, ensure_ascii=False, indent=2))


def render_human(version: str, ctx: DoctorContext, results: list[CheckResult]) -> None:
    console = Console()
    role = _role(ctx).upper()
    console.print(f"[bold cyan]Polily Doctor[/] — v{version}  ▶ analyzing: [bold]{role}[/] instance")
    console.print(f"[dim]{ctx.db_path}  (tier={ctx.data_dir_tier}, label={ctx.launchd_label})[/]\n")
    last_group = None
    for r in results:
        if r.group != last_group:
            console.rule(f"[bold]{r.group}[/]")
            last_group = r.group
        console.print(f"  {_MARK[r.severity]}  {r.title}" + (f" — {r.detail}" if r.detail else ""))
        if r.fix_hint and r.severity in (Severity.WARN, Severity.CRITICAL):
            console.print(f"      [dim]→ {r.fix_hint}[/]")
    s = _summary(results)
    console.print(
        f"\n[bold]{s['ok']} ok · {s['warn']} warn · {s['critical']} critical[/]"
        f"  (exit {s['exit_code']})"
    )
