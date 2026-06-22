from __future__ import annotations

from collections.abc import Callable

# Ordered registry. Group 0 (instance) MUST be first. Later tasks append.
REGISTRY: list[Callable] = []
