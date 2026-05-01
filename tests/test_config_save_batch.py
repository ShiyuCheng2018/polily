"""Tests for `polily.core.config.save_knob_batch` — atomic multi-key writes.

Round 4 (v0.10.0 TUI Config) — back-end for the WeightFamilyEditModal.
The modal commits 3-5 weight leaves at once and the algorithmic invariant
(`sum == 1.0`) only makes sense when all of those writes are applied
atomically. A partial write (3 of 5 succeed, last 2 fail Pydantic) would
leave the db in a "broken sum" intermediate state.

Contract:
  - All upserts succeed together OR rollback together (BEGIN IMMEDIATE)
  - Single Pydantic validation over the merged config (not N validations)
  - Each key MUST be in TERRITORY_A (defense-in-depth, mirrors save_knob)
  - Empty dict is a no-op (no transaction churn)
"""
from __future__ import annotations

import pytest

from polily.core.config import (
    ConfigValidationError,
    save_knob,
    save_knob_batch,
)
from polily.core.config_store import (
    ConfigSaveError,
    ensure_seeded,
    load_all,
)
from polily.core.db import PolilyDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "polily.db"
    d = PolilyDB(db_path)
    ensure_seeded(d)
    yield d
    d.close()


def test_save_knob_batch_empty_dict_is_noop(db):
    """Empty updates → no-op, no transaction churn, no rows touched."""
    before = load_all(db)
    save_knob_batch(db, {})
    after = load_all(db)
    assert before == after


def test_save_knob_batch_writes_all_keys_atomically(db):
    """Happy path: 3 weight leaves change → all 3 visible in db post-call."""
    updates = {
        "movement.weights.crypto.magnitude.price_z_score": 0.20,
        "movement.weights.crypto.magnitude.book_imbalance": 0.20,
        "movement.weights.crypto.magnitude.fair_value_divergence": 0.30,
    }
    save_knob_batch(db, updates)

    flat = load_all(db)
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.20
    assert flat["movement.weights.crypto.magnitude.book_imbalance"] == 0.20
    assert flat["movement.weights.crypto.magnitude.fair_value_divergence"] == 0.30


def test_save_knob_batch_partial_family_still_works(db):
    """Only 2 of 5 leaves in a family: still atomic if Pydantic accepts.

    The sum=1 invariant is enforced at the modal layer, not Pydantic — so
    partial writes that drift the sum are ALLOWED at the API level (the
    modal won't issue them, but a future caller might).
    """
    updates = {
        "movement.weights.crypto.magnitude.price_z_score": 0.50,
        "movement.weights.crypto.magnitude.book_imbalance": 0.50,
    }
    save_knob_batch(db, updates)

    flat = load_all(db)
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.50
    assert flat["movement.weights.crypto.magnitude.book_imbalance"] == 0.50
    # Untouched leaves keep their defaults.
    assert flat[
        "movement.weights.crypto.magnitude.fair_value_divergence"
    ] == 0.40


def test_save_knob_batch_rolls_back_on_pydantic_failure(db):
    """If Pydantic rejects the merged config, NO rows are written.

    Use a value that violates a Field constraint: wallet.starting_balance
    has Field(ge=1.0). Pair it with a valid weight write — both must
    rollback together (atomicity).
    """
    before = load_all(db)
    updates = {
        "movement.weights.crypto.magnitude.price_z_score": 0.30,  # valid
        "wallet.starting_balance": 0.5,  # invalid: ge=1.0
    }
    with pytest.raises(ConfigValidationError):
        save_knob_batch(db, updates)

    after = load_all(db)
    # Pre-state proven to be unchanged: assert exact dict equality on the
    # subset we touched. (Drift in updated_at columns isn't visible via
    # load_all; we just check the value field.)
    assert after[
        "movement.weights.crypto.magnitude.price_z_score"
    ] == before["movement.weights.crypto.magnitude.price_z_score"]
    assert after["wallet.starting_balance"] == before["wallet.starting_balance"]


def test_save_knob_batch_rejects_non_territory_a_key(db):
    """Defense-in-depth: HIDDEN_IN_TUI / EPHEMERAL keys are rejected.

    Mirrors `save_knob`'s contract through `upsert(EPHEMERAL_FIELDS)` and
    the `is_territory_a` gate at modal construction. A future caller
    that bypasses the modal must still be blocked.
    """
    before = load_all(db)
    updates = {
        "movement.weights.crypto.magnitude.price_z_score": 0.30,
        "tui.heartbeat_seconds": 999.0,  # HIDDEN_IN_TUI
    }
    with pytest.raises((ConfigSaveError, ValueError)):
        save_knob_batch(db, updates)

    after = load_all(db)
    # Atomic: the valid key is also NOT written — both rollback.
    assert after[
        "movement.weights.crypto.magnitude.price_z_score"
    ] == before["movement.weights.crypto.magnitude.price_z_score"]


def test_save_knob_batch_rejects_ephemeral_key(db):
    """EPHEMERAL_FIELDS (api.user_agent) must be rejected — same gate."""
    updates = {
        "api.user_agent": "polily/forged",
    }
    with pytest.raises((ConfigSaveError, ValueError)):
        save_knob_batch(db, updates)

    flat = load_all(db)
    # api.user_agent is filtered from load_all output — verify by absence.
    assert "api.user_agent" not in flat


def test_save_knob_batch_single_validation_pass(db, monkeypatch):
    """Single PolilyConfig.model_validate over the merged dict, not N validations.

    Counts the validation calls; for 5 updates we expect exactly 1 (not 5).
    """
    from polily.core import config as config_mod

    call_count = {"n": 0}
    original = config_mod.PolilyConfig.model_validate

    def counting_validate(cls_or_data, *args, **kwargs):
        call_count["n"] += 1
        # model_validate is a classmethod — when called as
        # `PolilyConfig.model_validate(data)`, the first positional arg
        # is the data dict (cls is bound). Forward as-is.
        return original(cls_or_data, *args, **kwargs)

    monkeypatch.setattr(
        config_mod.PolilyConfig, "model_validate", counting_validate,
    )

    updates = {
        "movement.weights.crypto.magnitude.price_z_score": 0.20,
        "movement.weights.crypto.magnitude.book_imbalance": 0.20,
        "movement.weights.crypto.magnitude.fair_value_divergence": 0.30,
        "movement.weights.crypto.magnitude.underlying_z_score": 0.20,
        "movement.weights.crypto.magnitude.cross_divergence": 0.10,
    }
    save_knob_batch(db, updates)

    assert call_count["n"] == 1, (
        f"expected 1 validation call for 5 updates (single merged validate), "
        f"got {call_count['n']}"
    )


def test_save_knob_batch_independent_from_save_knob(db):
    """save_knob_batch is independent from save_knob — they don't share
    state, and a save_knob call between two save_knob_batch calls works.
    """
    save_knob(db, "movement.magnitude_threshold", 60)
    save_knob_batch(db, {
        "movement.weights.crypto.magnitude.price_z_score": 0.25,
    })
    save_knob(db, "movement.quality_threshold", 50)

    flat = load_all(db)
    assert flat["movement.magnitude_threshold"] == 60
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.25
    assert flat["movement.quality_threshold"] == 50
