from __future__ import annotations

import plistlib
from pathlib import Path

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity

_STALE_SECONDS = 90.0  # 3× the 30s poll interval


def _is_running() -> bool:
    # NOTE: is_daemon_running()/get_daemon_pid() take NO args — they resolve the
    # label live from paths.launchd_label() (env-driven), same source build_context
    # used for ctx.launchd_label, so they stay consistent.
    from polily.daemon.launchctl_query import is_daemon_running
    return is_daemon_running()


def _poll_log_age_seconds(ctx: DoctorContext) -> float | None:
    """Seconds since the newest poll-v*.log was written (by mtime), or None."""
    import time
    logs = list(ctx.log_dir.glob("poll-v*.log"))
    if not logs:
        return None
    newest = max(logs, key=lambda p: p.stat().st_mtime)
    return time.time() - newest.stat().st_mtime


def _monitored_freshness(ctx: DoctorContext) -> tuple[int, float | None]:
    """Return (monitored_market_count, seconds_since_newest_update or None)."""
    conn = ctx.ro_conn()
    if conn is None:
        return (0, None)
    row = conn.execute(
        "SELECT COUNT(*) AS n, "
        "  (julianday('now') - julianday(MAX(m.updated_at))) * 86400.0 AS age_s "
        "FROM markets m JOIN event_monitors em ON m.event_id = em.event_id "
        "WHERE em.auto_monitor = 1 AND m.active = 1 AND m.closed = 0",
    ).fetchone()
    return (row["n"] or 0, row["age_s"])


def _newest_poll_log_version(ctx: DoctorContext) -> str | None:
    # Sort by mtime, NOT filename: lexical sort puts "poll-v0.9.0" AFTER
    # "poll-v0.12.4" ("9" > "1"), reading a stale log after a minor bump.
    logs = list(ctx.log_dir.glob("poll-v*.log"))
    if not logs:
        return None
    newest = max(logs, key=lambda p: p.stat().st_mtime)
    return newest.name[len("poll-v"):].rsplit("-", 2)[0]  # poll-v<version>-<ts>.log


def daemon_checks(ctx: DoctorContext) -> list[CheckResult]:
    if ctx.platform != "darwin":
        return [CheckResult(id=f"daemon.{k}", title=t, severity=Severity.SKIPPED,
                            detail="launchd is macOS-only", group="daemon")
                for k, t in [("registered", "Daemon registered"),
                             ("polling_fresh", "Daemon polling"),
                             ("plist_valid", "Daemon plist"),
                             ("version_drift", "Daemon version")]]

    out: list[CheckResult] = []
    running = _is_running()
    out.append(CheckResult(
        id="daemon.registered", title="Daemon registered",
        severity=Severity.OK if running else Severity.CRITICAL,
        detail=f"{ctx.launchd_label} {'alive' if running else 'not registered'}",
        fix_hint="polily scheduler restart" if not running else None, group="daemon"))

    # Primary signal: DB poll-freshness. Cross-check (design §6): poll-log mtime,
    # so we (a) still report liveness when there are 0 monitored markets, and
    # (b) catch "DB stale-but-not-wedged" vs "log advancing but DB writes lag".
    n, age = _monitored_freshness(ctx)
    log_age = _poll_log_age_seconds(ctx)
    if n == 0:
        if log_age is None:
            sev, detail = Severity.INFO, "no monitored markets; daemon has not written a poll log yet"
        elif log_age > _STALE_SECONDS:
            sev, detail = Severity.WARN, (
                f"no monitored markets, and last poll log was {log_age/60:.1f} min ago")
        else:
            sev, detail = Severity.OK, "daemon ticking (no monitored markets to poll)"
    elif age is None:
        sev, detail = Severity.WARN, f"{n} monitored markets but no update timestamp"
    elif age > _STALE_SECONDS:
        sev, detail = Severity.CRITICAL, (
            f"{n} monitored markets last updated {age/60:.1f} min ago — poll wedged?")
    elif log_age is not None and log_age > _STALE_SECONDS:
        sev, detail = Severity.WARN, (
            f"DB fresh but poll log is {log_age/60:.1f} min stale — writes may be lagging")
    else:
        sev, detail = Severity.OK, f"{n} monitored markets fresh ({age:.0f}s ago)"
    out.append(CheckResult(
        id="daemon.polling_fresh", title="Daemon polling", severity=sev, detail=detail,
        fix_hint="polily scheduler restart" if sev == Severity.CRITICAL else None,
        value={"monitored": n, "db_age_seconds": age, "log_age_seconds": log_age},
        group="daemon"))

    plist = Path.home() / "Library" / "LaunchAgents" / f"{ctx.launchd_label}.plist"
    if not plist.exists():
        out.append(CheckResult(id="daemon.plist_valid", title="Daemon plist",
                               severity=Severity.INFO, detail="no plist (daemon not installed)",
                               group="daemon"))
    else:
        try:
            data = plistlib.loads(plist.read_bytes())
            args = data.get("ProgramArguments", [])
            keepalive = data.get("KeepAlive")
            stderr = data.get("StandardErrorPath", "")
            # "--config" = the v0.10.0-removed flag (legacy plist crash-loops). "scheduler"
            # absent = a malformed ProgramArguments for a com.polily.scheduler plist; real
            # plists always contain it ([python, -m, polily.cli, scheduler, run]).
            bad_args = "--config" in args or "scheduler" not in args
            bad_ka = not (keepalive is True)
            if bad_args or bad_ka:
                sev, detail = Severity.CRITICAL, (
                    "stale ProgramArguments (legacy --config)" if bad_args
                    else "KeepAlive is not boolean True")
            elif stderr.endswith("/dev/null"):
                sev, detail = Severity.WARN, "stderr → /dev/null (tracebacks lost)"
            else:
                sev, detail = Severity.OK, "plist looks current"
            out.append(CheckResult(id="daemon.plist_valid", title="Daemon plist",
                                   severity=sev, detail=detail,
                                   fix_hint="polily scheduler restart"
                                   if sev != Severity.OK else None, group="daemon"))
        except Exception as e:
            out.append(CheckResult(id="daemon.plist_valid", title="Daemon plist",
                                   severity=Severity.WARN, detail=f"unparseable: {e}",
                                   group="daemon"))

    from polily import __version__
    daemon_ver = _newest_poll_log_version(ctx)
    if daemon_ver is None:
        out.append(CheckResult(id="daemon.version_drift", title="Daemon version",
                               severity=Severity.INFO, detail="daemon has not run yet",
                               group="daemon"))
    else:
        drift = daemon_ver != __version__
        out.append(CheckResult(
            id="daemon.version_drift", title="Daemon version",
            severity=Severity.WARN if drift else Severity.OK,
            detail=f"daemon running v{daemon_ver}, installed v{__version__}",
            fix_hint="polily scheduler restart" if drift else None,
            value={"daemon": daemon_ver, "installed": __version__}, group="daemon"))

    return out
