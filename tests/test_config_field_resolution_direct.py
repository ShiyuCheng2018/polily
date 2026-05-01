"""v0.10.1 — direct unit tests for _resolve_field_annotation +
_coerce_value. Vegeta R3 review noted these helpers had only indirect
coverage via TUI modal happy-path. This file pins their contract.
"""
from __future__ import annotations

import pytest

from polily.core.config import _coerce_value, _resolve_field_annotation

# --- _resolve_field_annotation -----------------------------------------------

def test_resolve_movement_daily_analysis_limit_returns_int():
    """Bare scalar int annotation (`daily_analysis_limit: int = 10`)."""
    assert _resolve_field_annotation("movement.daily_analysis_limit") is int


def test_resolve_wallet_starting_balance_returns_float():
    assert _resolve_field_annotation("wallet.starting_balance") is float


def test_resolve_unknown_keypath_returns_none():
    """Non-existent paths return None (not raise) so callers can show a
    graceful 'cannot locate type' message."""
    assert _resolve_field_annotation("does.not.exist") is None


def test_resolve_empty_keypath_returns_none():
    assert _resolve_field_annotation("") is None


def test_resolve_handles_nested_dict_of_basemodel():
    """movement.weights.<market_type>.<family>.<signal> traverses
    dict[str, BaseModel] before finding the float leaf."""
    assert _resolve_field_annotation(
        "movement.weights.crypto.magnitude.price_z_score",
    ) is float


# --- _coerce_value: int -------------------------------------------------------

def test_coerce_int_accepts_integer_string():
    assert _coerce_value("42", int) == 42


def test_coerce_int_rejects_decimal_string():
    """0.5 is not an int — Python's int() doesn't auto-truncate."""
    with pytest.raises(ValueError, match="无法解析"):
        _coerce_value("0.5", int)


def test_coerce_int_rejects_scientific_notation():
    """'1e10' is not a valid int literal — int() raises."""
    with pytest.raises(ValueError):
        _coerce_value("1e10", int)


def test_coerce_int_rejects_garbage():
    with pytest.raises(ValueError):
        _coerce_value("abc", int)


# --- _coerce_value: float -----------------------------------------------------

def test_coerce_float_accepts_decimal():
    assert _coerce_value("0.5", float) == 0.5


def test_coerce_float_accepts_scientific_notation():
    assert _coerce_value("1e10", float) == 1e10


def test_coerce_float_accepts_integer_string():
    assert _coerce_value("42", float) == 42.0


def test_coerce_float_accepts_negative():
    assert _coerce_value("-0.5", float) == -0.5


# --- _coerce_value: bool ------------------------------------------------------
# Verified at config.py:_coerce_value — accepts true/1/yes/on / false/0/no/off

@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"])
def test_coerce_bool_accepts_truthy_forms(raw):
    assert _coerce_value(raw, bool) is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no", "NO", "off"])
def test_coerce_bool_accepts_falsy_forms(raw):
    assert _coerce_value(raw, bool) is False


@pytest.mark.parametrize("raw", ["maybe", "x", "T", "F", "2"])
def test_coerce_bool_rejects_garbage(raw):
    with pytest.raises(ValueError, match="无法解析"):
        _coerce_value(raw, bool)


# --- _coerce_value: str + unknown -------------------------------------------

def test_coerce_str_passthrough():
    assert _coerce_value("hello", str) == "hello"


def test_coerce_str_passthrough_empty():
    assert _coerce_value("", str) == ""


def test_coerce_unknown_annotation_raises():
    """Annotation that's not int/float/bool/str — currently raises with
    '不支持的类型'. Pin this so a future change is intentional."""
    with pytest.raises(ValueError, match="不支持的类型"):
        _coerce_value("anything", list)
