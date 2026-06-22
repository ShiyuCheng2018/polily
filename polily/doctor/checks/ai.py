from __future__ import annotations

import contextlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity


def ai_checks(ctx: DoctorContext) -> list[CheckResult]:
    out: list[CheckResult] = []

    # --- ai.claude_cli ---
    claude = shutil.which("claude")
    if not claude:
        out.append(CheckResult(id="ai.claude_cli", title="Claude CLI", severity=Severity.WARN,
                               detail="not on PATH — AI analysis will fail",
                               fix_hint="install Claude Code CLI (bundled with your subscription)",
                               group="ai"))
    else:
        ver = ""
        with contextlib.suppress(Exception):
            ver = subprocess.run([claude, "--version"], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
        out.append(CheckResult(id="ai.claude_cli", title="Claude CLI", severity=Severity.OK,
                               detail=f"{claude} {ver}", value={"path": claude, "version": ver},
                               group="ai"))

    # --- ai.daemon_claude_path (darwin-only) ---
    if ctx.platform != "darwin":
        out.append(CheckResult(id="ai.daemon_claude_path", title="Daemon claude path",
                               severity=Severity.SKIPPED, detail="launchd is macOS-only", group="ai"))
    else:
        plist = Path.home() / "Library" / "LaunchAgents" / f"{ctx.launchd_label}.plist"
        if not plist.exists():
            out.append(CheckResult(id="ai.daemon_claude_path", title="Daemon claude path",
                                   severity=Severity.INFO, detail="no plist found", group="ai"))
        else:
            try:
                env = (plistlib.loads(plist.read_bytes()).get("EnvironmentVariables") or {})
                dc = env.get("POLILY_CLAUDE_CLI")
                if not dc:
                    sev, detail = Severity.WARN, "plist missing POLILY_CLAUDE_CLI (pre-v0.9.1)"
                elif not Path(dc).exists():
                    sev, detail = Severity.CRITICAL, f"plist claude path missing: {dc}"
                elif claude and dc != claude:
                    sev, detail = Severity.WARN, f"daemon uses {dc}, shell uses {claude}"
                else:
                    sev, detail = Severity.OK, dc
                out.append(CheckResult(id="ai.daemon_claude_path", title="Daemon claude path",
                                       severity=sev, detail=detail,
                                       fix_hint="polily scheduler restart"
                                       if sev != Severity.OK else None, group="ai"))
            except Exception as e:
                out.append(CheckResult(id="ai.daemon_claude_path", title="Daemon claude path",
                                       severity=Severity.WARN, detail=f"plist parse error: {e}",
                                       group="ai"))

    # --- ai.auth (heuristic from ~/.claude.json) ---
    cfg = Path.home() / ".claude.json"
    sev, detail = Severity.INFO, "no ~/.claude.json (auth state unknown)"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            has_sub = data.get("hasAvailableSubscription")
            has_oauth = bool(data.get("oauthAccount"))
            if has_sub is False:
                sev, detail = Severity.WARN, "hasAvailableSubscription=False (auth may be lapsed)"
            elif has_oauth:
                sev, detail = Severity.OK, "oauth account present"
            else:
                sev, detail = Severity.INFO, "~/.claude.json present but subscription status unclear"
        except Exception:
            sev, detail = Severity.WARN, "~/.claude.json unparseable"
    out.append(CheckResult(id="ai.auth", title="Claude auth (heuristic)", severity=sev,
                           detail=detail,
                           fix_hint="run `claude` interactively to confirm login"
                           if sev == Severity.WARN else None, group="ai"))

    # --- ai.recent_failures ---
    conn = ctx.ro_conn()
    if conn is None:
        out.append(CheckResult(id="ai.recent_failures", title="Recent AI failures",
                               severity=Severity.SKIPPED, detail="db not readable", group="ai"))
    else:
        rows = conn.execute(
            "SELECT error FROM scan_logs WHERE type='analyze' AND status='failed' "
            "AND datetime(finished_at) >= datetime('now','-1 day')").fetchall()
        nfail = len(rows)
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM scan_logs WHERE type='analyze' "
            "AND datetime(finished_at) >= datetime('now','-1 day')").fetchone()["n"]
        if nfail == 0:
            sev, detail = Severity.OK, "no failed analyses in last 24h"
        elif total and nfail >= total:
            sev, detail = Severity.CRITICAL, f"all {nfail} recent analyses failed"
        else:
            sev, detail = Severity.WARN, f"{nfail} failed analyses in last 24h"
        sample = rows[0]["error"] if rows else None
        out.append(CheckResult(id="ai.recent_failures", title="Recent AI failures",
                               severity=sev,
                               detail=detail + (f" (e.g. {sample})" if sample else ""),
                               value={"failed_24h": nfail, "sample": sample}, group="ai"))

    # --- ai.mcp_allowlist ---
    try:
        from polily.util.claude_config import list_user_mcp_servers
        servers = list_user_mcp_servers()
        out.append(CheckResult(id="ai.mcp_allowlist", title="MCP allowlist",
                               severity=Severity.INFO,
                               detail=f"agent MCP servers: {servers or 'none'}",
                               value={"servers": servers}, group="ai"))
    except Exception as e:
        out.append(CheckResult(id="ai.mcp_allowlist", title="MCP allowlist",
                               severity=Severity.WARN, detail=f"~/.claude.json unreadable: {e}",
                               group="ai"))

    # --- ai.live_probe ---
    if not ctx.live:
        out.append(CheckResult(id="ai.live_probe", title="Claude -p smoke test",
                               severity=Severity.SKIPPED,
                               detail="run with --live (hits the API, uses quota)", group="ai"))
    elif not claude:
        out.append(CheckResult(id="ai.live_probe", title="Claude -p smoke test",
                               severity=Severity.CRITICAL, detail="claude not installed", group="ai"))
    else:
        try:
            proc = subprocess.run(
                [claude, "-p", "reply with the single word OK", "--output-format", "json"],
                capture_output=True, text=True, timeout=60)
            parsed = json.loads(proc.stdout)
            ok = isinstance(parsed, list) and any(
                isinstance(e, dict) and e.get("type") == "result" for e in parsed)
            out.append(CheckResult(id="ai.live_probe", title="Claude -p smoke test",
                                   severity=Severity.OK if ok else Severity.CRITICAL,
                                   detail="contract OK" if ok else "unexpected output envelope",
                                   group="ai"))
        except Exception as e:
            out.append(CheckResult(id="ai.live_probe", title="Claude -p smoke test",
                                   severity=Severity.CRITICAL, detail=f"{type(e).__name__}: {e}",
                                   fix_hint="run `claude` interactively to confirm auth", group="ai"))

    return out
