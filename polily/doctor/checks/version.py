from __future__ import annotations

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity


def _installed() -> str:
    from polily import __version__
    return __version__


def _pypi_latest() -> str | None:
    from polily.core.update_check import fetch_latest_pypi_version
    return fetch_latest_pypi_version(timeout=5.0)


def _daemon_version(ctx: DoctorContext) -> str | None:
    # Reuse the daemon group's helper — single source of the mtime-sort logic (DRY).
    from polily.doctor.checks.daemon import _newest_poll_log_version
    return _newest_poll_log_version(ctx)


def version_checks(ctx: DoctorContext) -> list[CheckResult]:
    out: list[CheckResult] = []
    installed = _installed()
    is_dev_build = "+" in installed or ".dev" in installed
    out.append(CheckResult(id="version.installed", title="Installed version",
                           severity=Severity.INFO,
                           detail=installed + (" (dev/source build)" if is_dev_build else ""),
                           value={"version": installed}, group="version"))

    if ctx.offline:
        out.append(CheckResult(id="version.pypi_latest", title="PyPI latest",
                               severity=Severity.SKIPPED, detail="--offline", group="version"))
    elif is_dev_build:
        out.append(CheckResult(id="version.pypi_latest", title="PyPI latest",
                               severity=Severity.INFO,
                               detail="dev/source build — skipping PyPI compare", group="version"))
    else:
        latest = _pypi_latest()
        if latest is None:
            out.append(CheckResult(id="version.pypi_latest", title="PyPI latest",
                                   severity=Severity.INFO, detail="PyPI unreachable (offline?)",
                                   group="version"))
        else:
            try:
                from packaging.version import Version
                update = Version(latest) > Version(installed)
            except Exception:
                update = latest != installed
            out.append(CheckResult(id="version.pypi_latest", title="PyPI latest",
                                   severity=Severity.WARN if update else Severity.OK,
                                   detail=f"latest {latest}, installed {installed}",
                                   fix_hint="pipx upgrade polily" if update else None,
                                   value={"latest": latest, "installed": installed},
                                   group="version"))

    dv = _daemon_version(ctx)
    if dv is None:
        out.append(CheckResult(id="version.daemon_running", title="Daemon version",
                               severity=Severity.INFO, detail="daemon has not run yet",
                               group="version"))
    else:
        drift = dv != installed
        out.append(CheckResult(id="version.daemon_running", title="Daemon version",
                               severity=Severity.WARN if drift else Severity.OK,
                               detail=f"daemon v{dv}, installed v{installed}",
                               fix_hint="polily scheduler restart" if drift else None,
                               group="version"))
    return out
