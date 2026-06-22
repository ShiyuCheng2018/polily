from __future__ import annotations

import enum
from collections.abc import Iterable

from pydantic import BaseModel


class Severity(str, enum.Enum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"
    SKIPPED = "skipped"


# Exit-code weight: ok/info/skipped do not raise the code.
_EXIT_WEIGHT = {
    Severity.OK: 0,
    Severity.INFO: 0,
    Severity.SKIPPED: 0,
    Severity.WARN: 1,
    Severity.CRITICAL: 3,
}
# Display ordering for "worst".
_RANK = {Severity.OK: 0, Severity.INFO: 1, Severity.SKIPPED: 1,
         Severity.WARN: 2, Severity.CRITICAL: 3}


class CheckResult(BaseModel):
    id: str
    title: str
    severity: Severity
    detail: str = ""
    value: dict | None = None
    fix_hint: str | None = None
    verifiable: bool = True
    group: str


def severity_exit_code(severities: Iterable[Severity]) -> int:
    return max((_EXIT_WEIGHT[s] for s in severities), default=0)


def worst_severity(results: Iterable[CheckResult]) -> Severity:
    best = Severity.OK
    for r in results:
        if _RANK[r.severity] > _RANK[best]:
            best = r.severity
    return best
