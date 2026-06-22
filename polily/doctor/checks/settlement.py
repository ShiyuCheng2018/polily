from __future__ import annotations

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity

_UMA_WINDOW_HOURS = 6.0


def _skipped(cid, title):
    return CheckResult(id=cid, title=title, severity=Severity.SKIPPED,
                       detail="database not readable", group="settlement")


def settlement_checks(ctx: DoctorContext) -> list[CheckResult]:
    conn = ctx.ro_conn()
    if conn is None:
        return [_skipped("settle.stuck_resolutions", "Stuck settlements"),
                _skipped("settle.positions_on_settled", "Positions on settled markets")]

    out: list[CheckResult] = []

    rows = conn.execute(
        "SELECT m.market_id, "
        "  (julianday('now') - julianday(m.end_date)) * 24.0 AS age_h, "
        "  EXISTS(SELECT 1 FROM positions p WHERE p.market_id = m.market_id) AS held "
        "FROM markets m WHERE m.closed = 1 AND m.resolved_outcome IS NULL",
    ).fetchall()
    stuck = len(rows)
    # NULL/unparseable end_date → treat as past-window (conservative: surface it rather than hide it).
    past_window = [r for r in rows if (r["age_h"] is None or r["age_h"] > _UMA_WINDOW_HOURS)]
    held = [r for r in past_window if r["held"]]
    if stuck == 0:
        sev, detail = Severity.OK, "no unsettled closed markets"
    elif held:
        sev, detail = Severity.CRITICAL, (
            f"{len(held)} closed markets past the UMA window with your positions unsettled")
    elif past_window:
        sev, detail = Severity.WARN, f"{len(past_window)} closed markets past UMA window, unsettled"
    else:
        sev, detail = Severity.INFO, f"{stuck} closed markets within normal UMA settle window"
    out.append(CheckResult(
        id="settle.stuck_resolutions", title="Stuck settlements", severity=sev, detail=detail,
        fix_hint="polily scheduler restart   (re-runs the backfill sweep)"
                 if sev in (Severity.WARN, Severity.CRITICAL) else None,
        value={"stuck": stuck, "past_window": len(past_window), "with_positions": len(held)},
        group="settlement"))

    bad = conn.execute(
        "SELECT COUNT(*) AS n FROM positions p JOIN markets m ON p.market_id = m.market_id "
        "WHERE m.resolved_outcome IS NOT NULL",
    ).fetchone()["n"]
    out.append(CheckResult(
        id="settle.positions_on_settled", title="Positions on settled markets",
        severity=Severity.CRITICAL if bad else Severity.OK,
        detail=(f"{bad} open positions on already-resolved/void markets (should be 0)"
                if bad else "none"),
        fix_hint="inspect manually — a half-applied settlement or void market"
                 if bad else None,
        value={"count": bad}, group="settlement"))

    return out
