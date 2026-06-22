from __future__ import annotations

from pathlib import Path

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity


def _is_source_checkout(start: Path) -> Path | None:
    """Walk up from `start`; return the checkout root if found, else None."""
    for d in [start, *start.parents]:
        pj = d / "pyproject.toml"
        if pj.exists():
            try:
                if 'name = "polily"' in pj.read_text(encoding="utf-8"):
                    return d
            except OSError:
                pass
        # NOTE: the .envrc/POLILY_DATA_DIR signal is a secondary hint. A non-polily
        # dir whose .envrc mentions POLILY_DATA_DIR could match here, but the
        # `instance.dev_checkout_prod_data` trap also requires data_dir_tier=="default";
        # if POLILY_DATA_DIR is actually exported the tier is "env", so the realistic
        # case is neutralized. pyproject(name="polily") is the strong, precise signal.
        envrc = d / ".envrc"
        if envrc.exists():
            try:
                if "POLILY_DATA_DIR" in envrc.read_text(encoding="utf-8"):
                    return d
            except OSError:
                pass
    return None


def _running_from_checkout() -> Path | None:
    """Return checkout root if the imported polily package is a source/editable
    install (not under site-packages/pipx), else None."""
    import polily
    pkg = Path(polily.__file__).resolve().parent  # .../polily
    if "site-packages" in pkg.parts or "/pipx/" in str(pkg):
        return None
    return _is_source_checkout(pkg.parent)


def _plist_data_dir(label: str) -> str | None:
    import plistlib
    p = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not p.exists():
        return None
    try:
        data = plistlib.loads(p.read_bytes())
        return (data.get("EnvironmentVariables") or {}).get("POLILY_DATA_DIR")
    except Exception:
        return None


def instance_checks(ctx: DoctorContext) -> list[CheckResult]:
    out: list[CheckResult] = []
    role = "dev" if ctx.launchd_label.endswith(".dev") else "prod"

    out.append(CheckResult(
        id="instance.resolution", title="Active instance", severity=Severity.INFO,
        detail=f"{role} — {ctx.db_path} (tier={ctx.data_dir_tier})",
        value={"role": role, "data_dir": str(ctx.data_dir), "db_path": str(ctx.db_path),
               "log_dir": str(ctx.log_dir), "launchd_label": ctx.launchd_label,
               "tier": ctx.data_dir_tier},
        group="instance",
    ))

    checkout = _running_from_checkout()
    out.append(CheckResult(
        id="instance.binary", title="Running binary",
        severity=Severity.INFO,
        detail="dev (editable checkout)" if checkout else "prod (installed package)",
        value={"checkout": str(checkout) if checkout else None}, group="instance",
    ))

    cwd_checkout = _is_source_checkout(Path.cwd())
    trap = bool(cwd_checkout) and ctx.data_dir_tier == "default"
    out.append(CheckResult(
        id="instance.dev_checkout_prod_data",
        title="Dev checkout but PROD data dir",
        severity=Severity.CRITICAL if trap else Severity.OK,
        detail=("You are inside a polily source checkout but doctor resolved the PROD "
                "data dir (POLILY_DATA_DIR unset). Everything below is PROD."
                if trap else "no mismatch"),
        fix_hint="direnv allow   (or: export POLILY_DATA_DIR=$(pwd)/data)" if trap else None,
        value={"cwd_checkout": str(cwd_checkout) if cwd_checkout else None,
               "tier": ctx.data_dir_tier}, group="instance",
    ))

    bin_data_mismatch = bool(checkout) and ctx.data_dir_tier == "default"
    out.append(CheckResult(
        id="instance.binary_data_mismatch", title="Dev code vs PROD database",
        severity=Severity.CRITICAL if bin_data_mismatch else Severity.OK,
        detail=("Running the dev (editable) binary against the PROD database."
                if bin_data_mismatch else "binary and data dir consistent"),
        fix_hint="direnv allow, or run the pipx prod binary outside the checkout"
                 if bin_data_mismatch else None,
        group="instance",
    ))

    # discovered instances
    plat_default = Path.home() / "Library" / "Application Support" / "polily" / "polily.db" \
        if ctx.platform == "darwin" else None
    repo_db = (cwd_checkout / "data" / "polily.db") if cwd_checkout else None
    found = []
    for label, pth in [("active", ctx.db_path), ("repo", repo_db), ("platformdirs", plat_default)]:
        if pth and Path(pth).exists():
            found.append(str(pth))
    distinct = sorted(set(found))
    out.append(CheckResult(
        id="instance.discovered", title="Discovered databases",
        severity=Severity.WARN if len(distinct) > 1 else Severity.INFO,
        detail=(f"{len(distinct)} polily.db files exist (split-brain risk)"
                if len(distinct) > 1 else "single database"),
        value={"databases": distinct,
               "daemon_prod_data_dir": _plist_data_dir("com.polily.scheduler"),
               "daemon_dev_data_dir": _plist_data_dir("com.polily.scheduler.dev")},
        group="instance",
    ))

    # daemon (for the resolved label) must write the db doctor reads
    if ctx.platform == "darwin":
        daemon_dd = _plist_data_dir(ctx.launchd_label)
        match = daemon_dd is not None and Path(daemon_dd).resolve() == ctx.data_dir.resolve()
        if daemon_dd is None:
            sev, detail = Severity.INFO, f"no plist for {ctx.launchd_label} (daemon not installed)"
        elif match:
            sev, detail = Severity.OK, "daemon writes the database doctor is reading"
        else:
            sev, detail = Severity.CRITICAL, (
                f"daemon ({ctx.launchd_label}) data dir {daemon_dd} != doctor's {ctx.data_dir}")
        out.append(CheckResult(
            id="instance.daemon_data_dir_match", title="Daemon ↔ doctor DB match",
            severity=sev, detail=detail,
            fix_hint="align POLILY_DATA_DIR and `polily scheduler restart`"
                     if sev == Severity.CRITICAL else None, group="instance"))
    else:
        out.append(CheckResult(
            id="instance.daemon_data_dir_match", title="Daemon ↔ doctor DB match",
            severity=Severity.SKIPPED, detail="launchd is macOS-only", group="instance"))

    return out
