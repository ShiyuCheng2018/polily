from __future__ import annotations

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity

_TOL = 0.01


def _skip(cid, title):
    return CheckResult(id=cid, title=title, severity=Severity.SKIPPED,
                       detail="database not readable", group="wallet")


def wallet_checks(ctx: DoctorContext) -> list[CheckResult]:
    conn = ctx.ro_conn()
    if conn is None:
        return [_skip(c, t) for c, t in [
            ("wallet.singleton", "Wallet singleton"),
            ("wallet.cash_reconciles", "Cash ↔ ledger"),
            ("wallet.balance_chain", "Ledger balance chain"),
            ("positions.cost_basis", "Position cost basis"),
            ("positions.orphans", "Orphan positions"),
            ("wallet.totals", "Topup/withdraw totals")]]

    out: list[CheckResult] = []

    n = conn.execute("SELECT COUNT(*) AS n FROM wallet WHERE id = 1").fetchone()["n"]
    out.append(CheckResult(
        id="wallet.singleton", title="Wallet singleton",
        severity=Severity.OK if n == 1 else Severity.CRITICAL,
        detail="ok" if n == 1 else f"expected 1 wallet row, found {n}",
        fix_hint="polily reset --wallet-only" if n != 1 else None, group="wallet"))

    if n == 1:
        row = conn.execute(
            "SELECT w.cash_usd, w.starting_balance + COALESCE("
            "  (SELECT SUM(amount_usd) FROM wallet_transactions), 0.0) AS expected "
            "FROM wallet w WHERE w.id = 1").fetchone()
        drift = abs(row["cash_usd"] - row["expected"])
        out.append(CheckResult(
            id="wallet.cash_reconciles", title="Cash ↔ ledger",
            severity=Severity.OK if drift <= _TOL else Severity.CRITICAL,
            detail=f"cash {row['cash_usd']:.2f} vs ledger {row['expected']:.2f} (drift {drift:.2f})",
            fix_hint="ledger is source of truth — inspect recent wallet_transactions"
                     if drift > _TOL else None,
            value={"cash": row["cash_usd"], "expected": row["expected"]}, group="wallet"))

        last = conn.execute(
            "SELECT balance_after FROM wallet_transactions ORDER BY id DESC LIMIT 1").fetchone()
        if last is not None:
            d2 = abs(last["balance_after"] - row["cash_usd"])   # reuse reconcile row, no 2nd query
            out.append(CheckResult(
                id="wallet.balance_chain", title="Ledger balance chain",
                severity=Severity.OK if d2 <= _TOL else Severity.WARN,
                detail=f"last balance_after {last['balance_after']:.2f} vs cash {row['cash_usd']:.2f}",
                group="wallet"))
        else:
            out.append(CheckResult(id="wallet.balance_chain", title="Ledger balance chain",
                                   severity=Severity.OK, detail="empty ledger", group="wallet"))

        tot = conn.execute(
            "SELECT w.topup_total, w.withdraw_total, "
            "  COALESCE((SELECT SUM(amount_usd) FROM wallet_transactions WHERE type='TOPUP'),0) AS lt, "
            "  COALESCE((SELECT SUM(-amount_usd) FROM wallet_transactions WHERE type='WITHDRAW'),0) AS lw "
            "FROM wallet w WHERE w.id=1").fetchone()
        bad_tot = abs(tot["topup_total"] - tot["lt"]) > _TOL or abs(tot["withdraw_total"] - tot["lw"]) > _TOL
        out.append(CheckResult(
            id="wallet.totals", title="Topup/withdraw totals",
            severity=Severity.WARN if bad_tot else Severity.OK,
            detail="diverge from ledger" if bad_tot else "match ledger", group="wallet"))

    cb = conn.execute(
        "SELECT COUNT(*) AS n FROM positions WHERE ABS(cost_basis - shares*avg_cost) > ?",
        (_TOL,)).fetchone()["n"]
    out.append(CheckResult(
        id="positions.cost_basis", title="Position cost basis",
        severity=Severity.CRITICAL if cb else Severity.OK,
        detail=f"{cb} positions where cost_basis != shares×avg_cost" if cb else "consistent",
        fix_hint="recompute cost_basis = shares×avg_cost" if cb else None,
        value={"count": cb}, group="wallet"))

    orphans = conn.execute(
        "SELECT COUNT(*) AS n FROM positions p LEFT JOIN markets m ON p.market_id=m.market_id "
        "WHERE m.market_id IS NULL").fetchone()["n"]
    out.append(CheckResult(
        id="positions.orphans", title="Orphan positions",
        severity=Severity.CRITICAL if orphans else Severity.OK,
        detail=f"{orphans} positions reference a missing market" if orphans else "none",
        fix_hint="check PRAGMA foreign_keys / hand-edits" if orphans else None,
        value={"count": orphans}, group="wallet"))

    return out
