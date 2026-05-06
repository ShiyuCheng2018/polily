"""AF-5a (v0.11.7): stop_loss/take_profit schema with mandatory `side`.

The new shape is::

    stop_loss: {"side": "yes" | "no", "price": float}

Legacy fixtures stored bare floats. A backward-compat validator
normalizes legacy bare floats to {"side": "yes", "price": <value>} on
read so the TUI history view of pre-v0.11.7 analyses rows still works.
"""
from __future__ import annotations

import json

import pytest

from polily.agents.schemas import NarrativeWriterOutput, StopLossOrTakeProfit


def test_stop_loss_take_profit_new_dict_format():
    """Agent emits the new {side, price} dict; schema accepts it."""
    out = NarrativeWriterOutput(
        event_id="evt1",
        stop_loss={"side": "yes", "price": 0.55},
        take_profit={"side": "yes", "price": 0.92},
    )
    assert isinstance(out.stop_loss, StopLossOrTakeProfit)
    assert out.stop_loss.side == "yes"
    assert out.stop_loss.price == 0.55
    assert isinstance(out.take_profit, StopLossOrTakeProfit)
    assert out.take_profit.side == "yes"
    assert out.take_profit.price == 0.92


def test_stop_loss_take_profit_no_side_supported():
    """NO-side stop_loss is valid (you bought NO; stop when NO price drops)."""
    out = NarrativeWriterOutput(
        event_id="evt1",
        stop_loss={"side": "no", "price": 0.65},
    )
    assert out.stop_loss.side == "no"
    assert out.stop_loss.price == 0.65


def test_legacy_bare_float_normalized_to_yes_side():
    """Backward compat: pre-v0.11.7 analyses have bare floats. Schema
    must accept them and normalize to {side: "yes", price: <value>}.

    Why YES default: the v5 sample showed agent treated the bare float
    as a YES-side price, so YES is the documented legacy semantic.
    """
    out = NarrativeWriterOutput(
        event_id="evt1",
        stop_loss=0.55,         # legacy bare float
        take_profit=0.92,       # legacy bare float
    )
    assert isinstance(out.stop_loss, StopLossOrTakeProfit)
    assert out.stop_loss.side == "yes"
    assert out.stop_loss.price == 0.55
    assert isinstance(out.take_profit, StopLossOrTakeProfit)
    assert out.take_profit.side == "yes"
    assert out.take_profit.price == 0.92


def test_legacy_bare_int_normalized_too():
    """Defensive: legacy fixtures may have stored ints (e.g., 1 instead
    of 1.0). Validator coerces to float."""
    out = NarrativeWriterOutput(event_id="evt1", stop_loss=0)
    assert out.stop_loss.side == "yes"
    assert out.stop_loss.price == 0.0


def test_none_remains_none():
    """Discovery-mode analyses have stop_loss=None; preserve."""
    out = NarrativeWriterOutput(event_id="evt1", stop_loss=None)
    assert out.stop_loss is None


def test_invalid_side_rejected():
    """side must be 'yes' or 'no' — anything else fails validation."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NarrativeWriterOutput(
            event_id="evt1",
            stop_loss={"side": "maybe", "price": 0.5},
        )


def test_missing_side_in_dict_rejected():
    """If a dict is provided, `side` is mandatory. No silent default
    when caller chose to supply a dict — only bare-float legacy gets
    the default."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NarrativeWriterOutput(
            event_id="evt1",
            stop_loss={"price": 0.5},  # missing side
        )


def test_round_trip_serialization_preserves_dict_form():
    """JSON round-trip uses the new dict form, not legacy bare float."""
    out = NarrativeWriterOutput(
        event_id="evt1",
        stop_loss={"side": "no", "price": 0.65},
    )
    payload = out.model_dump(mode="json")
    assert payload["stop_loss"] == {"side": "no", "price": 0.65}

    # Deserialize back, still works
    again = NarrativeWriterOutput(**payload)
    assert again.stop_loss.side == "no"
    assert again.stop_loss.price == 0.65


def test_analysis_panel_renders_new_dict_format():
    """analysis_panel.py displays new schema as 'YES @ $0.55' style."""
    # The TUI render code reads .get("stop_loss") on a dict (model_dump
    # output). Verify the dict form serializes to a render-friendly shape.
    out = NarrativeWriterOutput(
        event_id="evt1",
        stop_loss={"side": "yes", "price": 0.55},
    )
    rendered = out.model_dump(mode="json")["stop_loss"]
    assert rendered["side"] == "yes"
    assert rendered["price"] == 0.55


def test_analysis_panel_renders_legacy_bare_float_gracefully():
    """When TUI loads a pre-v0.11.7 analyses row whose narrative_output
    JSON has a bare-float stop_loss, the schema validator normalizes
    it on read. The TUI dict access still finds the same shape."""
    legacy_payload = {"event_id": "evt1", "stop_loss": 0.55}
    out = NarrativeWriterOutput(**legacy_payload)
    # Even though we passed a bare float, model_dump produces the
    # normalized dict form.
    assert out.model_dump(mode="json")["stop_loss"] == {
        "side": "yes",
        "price": 0.55,
    }


def test_legacy_in_db_stored_json_deserialize():
    """Simulate the path: legacy JSON in analyses table → load → render."""
    # This is what's stored in DB for pre-v0.11.7 rows.
    legacy_db_json = json.dumps({
        "event_id": "evt1",
        "stop_loss": 0.55,
        "take_profit": 0.92,
    })
    payload = json.loads(legacy_db_json)
    out = NarrativeWriterOutput(**payload)
    assert out.stop_loss.price == 0.55
    assert out.take_profit.price == 0.92
    # Both default to YES side (legacy semantic per v5 sample).
    assert out.stop_loss.side == "yes"
    assert out.take_profit.side == "yes"


def test_extra_keys_in_dict_rejected():
    """`extra="forbid"` on StopLossOrTakeProfit rejects unknown keys.
    Catches typos in agent output (e.g., {"side": "yes", "price": 0.5,
    "comment": "x"}) instead of silently ignoring them — the field
    validator forwards the dict to StopLossOrTakeProfit which rejects
    extras."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NarrativeWriterOutput(
            event_id="evt1",
            stop_loss={"side": "yes", "price": 0.5, "comment": "extra"},
        )
