from __future__ import annotations

from collections.abc import Callable

from polily.doctor.checks.ai import ai_checks
from polily.doctor.checks.daemon import daemon_checks
from polily.doctor.checks.database import database_checks
from polily.doctor.checks.environment import environment_checks
from polily.doctor.checks.instance import instance_checks
from polily.doctor.checks.settlement import settlement_checks
from polily.doctor.checks.version import version_checks
from polily.doctor.checks.wallet import wallet_checks

REGISTRY: list[Callable] = [
    instance_checks,
    environment_checks,
    daemon_checks,
    settlement_checks,
    wallet_checks,
    ai_checks,
    database_checks,
    version_checks,
]
