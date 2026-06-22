from __future__ import annotations

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity

_EXPECTED_TABLES = {
    "events", "markets", "event_monitors", "analyses", "movement_log", "scan_logs",
    "wallet", "positions", "user_prefs", "wallet_transactions", "config", "user_strategy",
}
_LEGACY_TABLES = {"paper_trades", "notifications"}


def database_checks(ctx: DoctorContext) -> list[CheckResult]:
    conn = ctx.ro_conn()
    if conn is None:
        crit = CheckResult(id="db.openable", title="Database openable",
                           severity=Severity.CRITICAL,
                           detail=f"cannot open {ctx.db_path}",
                           fix_hint="check the path / POLILY_DATA_DIR; or `polily reset`",
                           group="database")
        skips = [CheckResult(id=c, title=t, severity=Severity.SKIPPED,
                             detail="db not openable", group="database")
                 for c, t in [("db.integrity", "DB integrity"), ("db.schema", "Schema"),
                              ("db.config_valid", "Config valid"), ("db.wal_mode", "WAL mode"),
                              ("db.strategy", "Strategy")]]
        return [crit, *skips]

    out: list[CheckResult] = [CheckResult(id="db.openable", title="Database openable",
                                          severity=Severity.OK, detail=str(ctx.db_path),
                                          group="database")]

    pragma = "integrity_check" if ctx.deep else "quick_check"
    res = conn.execute(f"PRAGMA {pragma}").fetchone()[0]
    out.append(CheckResult(id="db.integrity", title="DB integrity",
                           severity=Severity.OK if res == "ok" else Severity.CRITICAL,
                           detail=f"{pragma}: {res}",
                           fix_hint="`.recover` the DB or `polily reset`" if res != "ok" else None,
                           group="database"))

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    missing = _EXPECTED_TABLES - tables
    legacy = _LEGACY_TABLES & tables
    if missing:
        sev, detail = Severity.CRITICAL, f"missing tables: {sorted(missing)}"
    elif legacy:
        sev, detail = Severity.WARN, f"legacy tables present: {sorted(legacy)} (not booted by current code)"
    else:
        sev, detail = Severity.OK, "all expected tables present"
    out.append(CheckResult(id="db.schema", title="Schema", severity=sev, detail=detail,
                           fix_hint="launch polily once (idempotent _init_schema)"
                           if sev != Severity.OK else None, group="database"))

    # config validity — READ-ONLY: read raw rows + validate in memory.
    # Do NOT call config_store.load_all / load_config_from_db — load_all runs
    # `with db.transaction()` (needs a writable PolilyDB; verified config_store.py:312)
    # which violates the read-only contract. EPHEMERAL_FIELDS (config_store.py:105)
    # and _unflatten (config_store.py:255) DO exist and are pure.
    try:
        import json as _j
        from polily.core import config_store
        from polily.core.config import PolilyConfig
        rows = conn.execute("SELECT key_path, value FROM config").fetchall()
        flat = {r["key_path"]: _j.loads(r["value"]) for r in rows}
        flat = {k: v for k, v in flat.items() if k not in config_store.EPHEMERAL_FIELDS}
        PolilyConfig.model_validate(config_store._unflatten(flat))
        cfg_ok, cfg_detail = True, "config validates"
    except Exception as e:
        cfg_ok, cfg_detail = False, f"{type(e).__name__}: {e}"
    out.append(CheckResult(id="db.config_valid", title="Config valid",
                           severity=Severity.OK if cfg_ok else Severity.CRITICAL,
                           detail=cfg_detail,
                           fix_hint="polily config reset --all" if not cfg_ok else None,
                           group="database"))

    jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
    out.append(CheckResult(id="db.wal_mode", title="WAL mode",
                           severity=Severity.OK if jm == "wal" else Severity.WARN,
                           detail=f"journal_mode={jm}",
                           fix_hint="launch polily once to re-apply WAL" if jm != "wal" else None,
                           group="database"))

    # strategy
    try:
        act = conn.execute("SELECT value FROM config WHERE key_path='active_strategy'").fetchone()
        import json as _j
        active = _j.loads(act["value"]) if act else "official"
        if active == "user":
            row = conn.execute("SELECT text FROM user_strategy WHERE id=1").fetchone()
            empty = not (row and (row["text"] or "").strip())
            sev = Severity.WARN if empty else Severity.OK
            detail = "active=user but strategy text empty" if empty else "user strategy active"
        else:
            sev, detail = Severity.OK, "official strategy active"
        out.append(CheckResult(id="db.strategy", title="Strategy", severity=sev, detail=detail,
                               fix_hint="write a strategy in the TUI or switch to official"
                               if sev == Severity.WARN else None, group="database"))
    except Exception as e:
        out.append(CheckResult(id="db.strategy", title="Strategy", severity=Severity.WARN,
                               detail=f"{type(e).__name__}: {e}", group="database"))

    return out
