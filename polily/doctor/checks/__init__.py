from __future__ import annotations

from collections.abc import Callable

from polily.doctor.checks.instance import instance_checks

REGISTRY: list[Callable] = [
    instance_checks,
]
