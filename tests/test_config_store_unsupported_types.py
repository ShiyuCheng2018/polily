"""Unit tests for SF9 — _flatten_pydantic must fail loud on unsupported leaves.

Today PolilyConfig has no list-typed or Optional-None-valued leaves, so
none of these branches trigger. SF9 makes the failure mode loud the
moment a future schema-edit adds one — without it, list values would
JSON-encode through, _unflatten + model_validate would round-trip them,
and the TUI Edit modal would silently bypass validation (because
_resolve_field_annotation can't coerce list[int]).
"""
from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel

from polily.core.config import PolilyConfig
from polily.core.config_store import _flatten_pydantic


class _ListLeafInner(BaseModel):
    window: list[int] = [1, 2, 3]


class _ListLeafTop(BaseModel):
    inner: _ListLeafInner = _ListLeafInner()


class _NoneLeafInner(BaseModel):
    maybe_int: Optional[int] = None  # noqa: UP045 - explicit Optional for test


class _NoneLeafTop(BaseModel):
    inner: _NoneLeafInner = _NoneLeafInner()


def test_flatten_pydantic_rejects_list_typed_leaf():
    """list[int] field at a leaf position must raise NotImplementedError.

    Without this, _flatten_pydantic JSON-encodes the list silently, the
    db row stores it, _unflatten reverses it, model_validate accepts it
    — but the TUI Edit modal's _resolve_field_annotation/_coerce_value
    pair has no idea what to do with list[int]. Net effect: silent
    bypass of TUI-side validation. SF9 forces a deliberate decision
    (extend the helper with list handling, or hide the field) instead
    of letting the inconsistency ride.
    """
    with pytest.raises(NotImplementedError, match="sequence|list"):
        _flatten_pydantic(_ListLeafTop())


def test_flatten_pydantic_rejects_none_valued_leaf():
    """Optional[int] = None must raise — same reason as list:
    db round-trips JSON null, but TUI Edit modal can't render/edit None
    safely. Force the schema author to choose a non-Optional default.
    """
    with pytest.raises(NotImplementedError, match="None"):
        _flatten_pydantic(_NoneLeafTop())


def test_flatten_pydantic_accepts_current_polily_config():
    """Regression guard — every leaf in today's PolilyConfig must
    flatten without raising. If this fails, someone added an
    unsupported leaf and SF9's NotImplementedError fired correctly,
    but the schema needs a fix BEFORE merge (not a test relax).
    """
    flat = _flatten_pydantic(PolilyConfig())
    assert len(flat) == 48  # locked by test_config_store::test_flatten_pydantic_total_leaf_count_is_48
