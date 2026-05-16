"""Unit tests for `_resolve_field_annotation` and `_coerce_value` (SF8).

Pins the contract that:
  1. Optional[X] / Annotated[X, Field(...)] both resolve to the bare scalar
     type X — so live validation in the TUI Edit modal can correctly reject
     non-coercible input even on schema-evolution where someone slaps
     `Optional[int]` or `Annotated[float, Field(ge=1.0)]` on a leaf.
  2. _coerce_value rejects ambiguous bool / int input (e.g. "abc" against
     bool, "1.0" against int).
  3. Generic Union[int, str] (multiple non-None args) is returned as-is and
     _coerce_value raises the `不支持的类型` error — config knobs aren't
     supposed to be sum types.
"""
from __future__ import annotations

from typing import Annotated, Optional, Union

import pytest
from pydantic import BaseModel, Field

from polily.core.config import (
    PolilyConfig,
    _coerce_value,
    _resolve_field_annotation,
    _unwrap_annotation,
)
from polily.core.config_store import _flatten_pydantic

# --- _resolve_field_annotation: real PolilyConfig leaves ---


@pytest.mark.parametrize(
    "key_path",
    sorted(_flatten_pydantic(PolilyConfig()).keys()),
)
def test_resolve_field_annotation_for_every_polily_leaf(key_path: str):
    """Every leaf currently in PolilyConfig must resolve to a non-None
    scalar annotation. Catches regressions where a future schema change
    introduces an Optional/Annotated wrapping that breaks _coerce_value.
    """
    ann = _resolve_field_annotation(key_path)
    assert ann is not None, f"could not resolve {key_path}"
    # The set of acceptable scalar types — everything _coerce_value handles.
    assert ann in (int, float, str, bool), (
        f"{key_path} resolved to {ann!r}, expected scalar (int/float/str/bool)"
    )


# --- _resolve_field_annotation: synthetic Optional / Annotated cases ---


class _SyntheticInner(BaseModel):
    plain_int: int = 1
    plain_float: float = 1.0
    optional_int: Optional[int] = 5  # noqa: UP045 - explicit Union form for test
    annotated_float: Annotated[float, Field(ge=1.0)] = 1.5
    optional_annotated: Annotated[Optional[int], Field(description="x")] = None  # noqa: UP045
    union_int_str: Union[int, str] = 1  # noqa: UP007 - explicit Union form for test


class _SyntheticTop(BaseModel):
    inner: _SyntheticInner = _SyntheticInner()


def _resolve_via_synthetic(key_path: str, model_cls: type[BaseModel]):
    """Mimic the same walking logic on a synthetic model — needed because
    `_resolve_field_annotation` walks `PolilyConfig`, not arbitrary models.
    Re-uses the same internal helpers via temp monkeypatch in the actual test.
    """
    # We can't directly call `_resolve_field_annotation` against a
    # different root model — but we can verify the unwrap helper inside it
    # by patching PolilyConfig's schema in a focused way. Easier: just
    # call _coerce_value with the unwrapped annotation directly via the
    # public API. So instead this test verifies _coerce_value against
    # the wrapped annotations the way SF8's _unwrap_annotation should
    # produce post-fix. Acceptable because _resolve_field_annotation's
    # job is purely to feed _coerce_value.
    raise NotImplementedError("see direct tests below")


def test_resolve_unwraps_optional_annotation(monkeypatch):
    """Force _resolve_field_annotation to walk a synthetic model where one
    leaf is Optional[int]. After SF8, must return bare `int`.
    """
    # Patch PolilyConfig so the resolver walks our synthetic schema.
    monkeypatch.setattr(
        "polily.core.config.PolilyConfig", _SyntheticTop
    )
    ann = _resolve_field_annotation("inner.optional_int")
    assert ann is int, f"expected unwrapped int, got {ann!r}"


def test_resolve_unwraps_annotated_annotation(monkeypatch):
    """Annotated[float, Field(ge=1.0)] → bare float."""
    monkeypatch.setattr(
        "polily.core.config.PolilyConfig", _SyntheticTop
    )
    ann = _resolve_field_annotation("inner.annotated_float")
    assert ann is float, f"expected unwrapped float, got {ann!r}"


def test_resolve_unwraps_optional_annotated_combination(monkeypatch):
    """Annotated[Optional[int], Field(...)] → bare int.

    Both wrappings stripped in arbitrary order. This is the realistic
    Pydantic v2 idiom (`Field` lives inside `Annotated`).
    """
    monkeypatch.setattr(
        "polily.core.config.PolilyConfig", _SyntheticTop
    )
    ann = _resolve_field_annotation("inner.optional_annotated")
    assert ann is int, f"expected unwrapped int, got {ann!r}"


def test_resolve_passes_through_plain_scalars(monkeypatch):
    """Plain int / float without wrapping: unchanged."""
    monkeypatch.setattr(
        "polily.core.config.PolilyConfig", _SyntheticTop
    )
    assert _resolve_field_annotation("inner.plain_int") is int
    assert _resolve_field_annotation("inner.plain_float") is float


def test_resolve_returns_generic_union_as_is(monkeypatch):
    """Union[int, str] (multiple non-None args) is returned as-is.

    Per SF8 design — config knobs aren't supposed to be sum types, so
    we let _coerce_value raise `不支持的类型` downstream rather than
    inventing a coercion priority. Pin this behavior so future "fix"
    PRs don't silently start picking the first arg.
    """
    monkeypatch.setattr(
        "polily.core.config.PolilyConfig", _SyntheticTop
    )
    ann = _resolve_field_annotation("inner.union_int_str")
    # Returned as-is — Union[int, str] (not unwrapped to int or str alone).
    # We can't compare Unions with `is`, so check it's not a bare scalar.
    assert ann not in (int, str, float, bool), (
        f"Union[int, str] should NOT be unwrapped to a single arg; got {ann!r}"
    )


# --- _coerce_value: edge cases for SF8 ---


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on"])
def test_coerce_value_bool_truthy(raw: str):
    assert _coerce_value(raw, bool) is True


@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off"])
def test_coerce_value_bool_falsy(raw: str):
    assert _coerce_value(raw, bool) is False


def test_coerce_value_bool_rejects_garbage():
    """`abc` is not a valid bool literal — must raise, not silently default."""
    with pytest.raises(ValueError, match="bool"):
        _coerce_value("abc", bool)


def test_coerce_value_int_rejects_float_string():
    """`1.0` must NOT silently coerce to int — Python's int() doesn't
    accept it ("invalid literal for int() with base 10"), and we
    propagate that as ValueError. Pin this so a future "tolerant"
    refactor doesn't accept "1.0" → 1.
    """
    with pytest.raises(ValueError, match="int"):
        _coerce_value("1.0", int)


def test_coerce_value_rejects_unknown_annotation():
    """Generic Union or list types fall through to `不支持的类型`."""
    with pytest.raises(ValueError, match="不支持的类型"):
        _coerce_value("anything", Union[int, str])  # noqa: UP007


def test_coerce_value_int_happy_path():
    assert _coerce_value("42", int) == 42


def test_coerce_value_float_happy_path():
    assert _coerce_value("1.5", float) == 1.5


def test_coerce_value_str_passthrough():
    assert _coerce_value("hello", str) == "hello"


# --- _unwrap_annotation: Literal handling (v0.12.0) ---


def test_unwrap_annotation_literal_strs_folds_to_str():
    """`Literal["official", "user"]` (homogeneous str args) folds to `str`
    so `_coerce_value` can parse raw TUI input. Pydantic's Literal field
    constraint still rejects values outside the allowed set at validation
    time — `_coerce_value` only needs a coercible scalar type.
    """
    from typing import Literal

    assert _unwrap_annotation(Literal["official", "user"]) is str


def test_unwrap_annotation_literal_ints_folds_to_int():
    from typing import Literal

    assert _unwrap_annotation(Literal[1, 2, 3]) is int


def test_unwrap_annotation_literal_mixed_types_does_not_fold():
    """`Literal[1, "a"]` has heterogeneous args — must NOT fold to a single
    scalar (would silently drop type info). The implementation's `all-same-type`
    guard returns the Literal annotation unchanged in this case so downstream
    `_coerce_value` raises `不支持的类型` (the expected outcome — there's no
    sensible scalar coercion for mixed Literals).
    """
    from typing import Literal

    ann = _unwrap_annotation(Literal[1, "a"])
    # The annotation is returned unchanged (still Literal-shaped), not folded
    assert ann is not int
    assert ann is not str


def test_unwrap_annotation_literal_bool_int_corner_folds_to_int():
    """`Literal[1, True]`: Python's `isinstance(True, int)` is True, so the
    all-same-type guard with `args[0] = 1` (type int) accepts `True` as int.
    Folds to int. Pydantic's Literal field still validates that the actual
    value matches one of `{1, True}` at model_validate time — no silent
    boolean→int coercion at the user-facing layer.

    This test pins the corner-case behavior so a future "stricter" fold
    refactor doesn't break existing TUI paths inadvertently.
    """
    from typing import Literal

    assert _unwrap_annotation(Literal[1, True]) is int


def test_unwrap_annotation_literal_optional_chain():
    """`Literal["official", "user"] | None` should unwrap Optional first,
    then fold the inner Literal to str. Verifies the unwrap chain composes
    correctly when both Optional and Literal layers are present.
    """
    from typing import Literal

    assert _unwrap_annotation(Literal["official", "user"] | None) is str
