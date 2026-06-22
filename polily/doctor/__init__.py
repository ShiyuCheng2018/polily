# polily doctor package — runtime-health diagnostic. See model.py / context.py / render.py.
from __future__ import annotations

from polily.doctor.checks import REGISTRY  # re-export so tests/monkeypatch use one list

__all__ = ["run_doctor", "REGISTRY"]


def run_doctor(
    *, json: bool = False, live: bool = False, deep: bool = False,
    offline: bool = False, exit_zero: bool = False,
) -> int:
    from polily import __version__
    from polily.doctor.context import build_context
    from polily.doctor.model import CheckResult, Severity, severity_exit_code
    from polily.doctor.render import render_human, render_json

    ctx = build_context(live=live, deep=deep, offline=offline)

    results: list[CheckResult] = []
    for check in REGISTRY:
        try:
            r = check(ctx)
            if isinstance(r, list):
                results.extend(r)
            elif r is not None:
                results.append(r)
        except Exception as e:  # a check must never crash the whole run
            name = getattr(check, "__name__", "check")
            results.append(CheckResult(
                id=f"{name}.errored", title=f"{name} crashed",
                severity=Severity.CRITICAL, detail=f"{type(e).__name__}: {e}",
                group="errors",
            ))

    (render_json if json else render_human)(__version__, ctx, results)
    return 0 if exit_zero else severity_exit_code(r.severity for r in results)
