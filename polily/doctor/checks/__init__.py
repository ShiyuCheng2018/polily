from __future__ import annotations

from collections.abc import Callable

from polily.doctor.checks.instance import instance_checks

REGISTRY: list[Callable] = [
    instance_checks,
]

from polily.doctor.checks.environment import environment_checks
REGISTRY.append(environment_checks)

from polily.doctor.checks.daemon import daemon_checks
REGISTRY.append(daemon_checks)
