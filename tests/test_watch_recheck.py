"""Tests for watch recheck orchestration.

TODO: v0.5.0 — rewrite when recheck_market is rebuilt for event-first schema.
Currently recheck_market raises NotImplementedError.
"""

import pytest

from scanner.daemon.recheck import recheck_market


def test_recheck_raises_not_implemented(polily_db):
    """recheck_market is stubbed and should raise NotImplementedError."""
    with pytest.raises(NotImplementedError, match="v0.5.0"):
        recheck_market("0xabc", db=polily_db)
