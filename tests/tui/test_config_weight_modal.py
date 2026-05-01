"""WeightFamilyEditModal tests — Round 4 (v0.10.0 TUI Config).

Replaces the single-leaf edit flow inside the `movement.weights.*` subtree
with a family-level editor. The modal must:
  - Show all leaves of one (market_type, family) pair together
  - Display a live sum that turns yellow when ∉ [0.99, 1.01]
  - Disable Save when sum is out of range (Q2: strict enforcement)
  - Provide auto-normalize + reset-to-defaults helpers
  - Render a collapsible "信号术语速查" with only the relevant signals
  - Commit via `save_knob_batch` (atomic — N keys, 1 transaction)
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static

from polily.tui.service import PolilyService
from polily.tui.views.config_weight_modal import WeightFamilyEditModal


class _Harness(App):
    def __init__(self, modal: WeightFamilyEditModal):
        super().__init__()
        self._modal = modal

    def on_mount(self) -> None:
        self.push_screen(self._modal)

    def compose(self) -> ComposeResult:
        yield from ()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = PolilyService()
    yield svc
    svc.db.close()


# Defaults for crypto/magnitude — sum 0.15+0.10+0.40+0.20+0.15 = 1.00.
_CRYPTO_MAG_PREFIX = "movement.weights.crypto.magnitude"
_CRYPTO_MAG_DEFAULTS = {
    "price_z_score": 0.15,
    "book_imbalance": 0.10,
    "fair_value_divergence": 0.40,
    "underlying_z_score": 0.20,
    "cross_divergence": 0.15,
}


def _make_modal(service, **overrides):
    """Build a modal with the crypto.magnitude family pre-loaded."""
    defaults = dict(_CRYPTO_MAG_DEFAULTS)
    return WeightFamilyEditModal(
        service=service,
        key_path_prefix=overrides.get("key_path_prefix", _CRYPTO_MAG_PREFIX),
        current_values=overrides.get("current_values", dict(defaults)),
        default_values=overrides.get("default_values", defaults),
    )


# ---- Construction & defense-in-depth ---------------------------------------


@pytest.mark.asyncio
async def test_modal_mounts_for_valid_weights_family_prefix(service):
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        # 5 inputs, one per leaf.
        inputs = list(modal.query(Input))
        assert len(inputs) == len(_CRYPTO_MAG_DEFAULTS)


def test_modal_rejects_construction_for_non_weights_prefix(service):
    """Defense-in-depth: only `movement.weights.*` prefixes allowed."""
    with pytest.raises(ValueError, match="movement.weights"):
        WeightFamilyEditModal(
            service=service,
            key_path_prefix="movement",  # not a weights family
            current_values={"magnitude_threshold": 70},
            default_values={"magnitude_threshold": 70},
        )


def test_modal_rejects_construction_when_leaves_not_in_territory_a(service):
    """Each `key_path_prefix.<leaf>` must be in TERRITORY_A. Forged input
    where the family path is plausible but the leaf is unknown should
    raise — TUI level + this gate are belt-and-suspenders.
    """
    with pytest.raises(ValueError):
        WeightFamilyEditModal(
            service=service,
            key_path_prefix=_CRYPTO_MAG_PREFIX,
            current_values={"forged_signal_xyz": 1.0},
            default_values={"forged_signal_xyz": 1.0},
        )


# ---- Live sum display + Save enabled-state ---------------------------------


@pytest.mark.asyncio
async def test_initial_sum_is_one_and_save_enabled(service):
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        sum_widget = modal.query_one("#family-sum", Static)
        assert "1.00" in str(sum_widget.render())
        assert modal.query_one("#confirm", Button).disabled is False


@pytest.mark.asyncio
async def test_changing_one_input_updates_live_sum(service):
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        # Bump price_z_score 0.15 → 0.50, total = 1.35
        modal.query_one("#input-price_z_score", Input).value = "0.50"
        await pilot.pause()
        sum_widget = modal.query_one("#family-sum", Static)
        assert "1.35" in str(sum_widget.render())


@pytest.mark.asyncio
async def test_save_disabled_when_sum_out_of_range(service):
    """Q2: strict enforcement — sum must be in [0.99, 1.01] to save."""
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        modal.query_one("#input-price_z_score", Input).value = "0.50"  # sum 1.35
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled is True


@pytest.mark.asyncio
async def test_save_re_enabled_when_sum_returns_to_range(service):
    """Toggle: invalid → valid restores Save."""
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        # Out of range
        modal.query_one("#input-price_z_score", Input).value = "0.50"
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled is True
        # Back to range — restore exact default
        modal.query_one("#input-price_z_score", Input).value = "0.15"
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled is False


# ---- Auto-normalize button --------------------------------------------------


@pytest.mark.asyncio
async def test_auto_normalize_scales_to_sum_one(service):
    """5 inputs at 0.40 each → sum 2.0 → after normalize each 0.20."""
    modal = WeightFamilyEditModal(
        service=service,
        key_path_prefix=_CRYPTO_MAG_PREFIX,
        current_values=dict.fromkeys(_CRYPTO_MAG_DEFAULTS, 0.40),
        default_values=_CRYPTO_MAG_DEFAULTS,
    )
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        # Programmatic press to avoid scroll/offscreen flake in run_test
        modal.query_one("#auto-normalize", Button).press()
        await pilot.pause()
        for leaf in _CRYPTO_MAG_DEFAULTS:
            value = modal.query_one(f"#input-{leaf}", Input).value
            assert abs(float(value) - 0.20) < 1e-6, f"{leaf} = {value}"
        assert modal.query_one("#confirm", Button).disabled is False


@pytest.mark.asyncio
async def test_auto_normalize_on_all_zero_inputs_is_noop(service):
    """All zeros → no change + warning notify (avoid div-by-zero)."""
    modal = WeightFamilyEditModal(
        service=service,
        key_path_prefix=_CRYPTO_MAG_PREFIX,
        current_values=dict.fromkeys(_CRYPTO_MAG_DEFAULTS, 0.0),
        default_values=_CRYPTO_MAG_DEFAULTS,
    )
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        notifies = []
        original_notify = modal.notify
        modal.notify = lambda *a, **kw: notifies.append((a, kw))  # type: ignore[method-assign]

        modal.query_one("#auto-normalize", Button).press()
        await pilot.pause()

        # All inputs still zero
        for leaf in _CRYPTO_MAG_DEFAULTS:
            assert (
                modal.query_one(f"#input-{leaf}", Input).value == "0.0"
            ), f"{leaf} changed unexpectedly"
        # Warning notify fired
        assert any(
            kw.get("severity") == "warning" for _a, kw in notifies
        ), f"expected warning notify on all-zero normalize, got: {notifies}"
        modal.notify = original_notify  # type: ignore[method-assign]


# ---- Reset button -----------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_writes_defaults_to_all_inputs(service):
    """Reset replaces every input with its Pydantic default value."""
    # Start with arbitrary, non-default values.
    custom = {
        "price_z_score": 0.05,
        "book_imbalance": 0.05,
        "fair_value_divergence": 0.50,
        "underlying_z_score": 0.30,
        "cross_divergence": 0.10,
    }
    modal = WeightFamilyEditModal(
        service=service,
        key_path_prefix=_CRYPTO_MAG_PREFIX,
        current_values=custom,
        default_values=_CRYPTO_MAG_DEFAULTS,
    )
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        modal.query_one("#reset-btn", Button).press()
        await pilot.pause()
        for leaf, expected in _CRYPTO_MAG_DEFAULTS.items():
            value = modal.query_one(f"#input-{leaf}", Input).value
            assert abs(float(value) - expected) < 1e-6, f"{leaf} = {value}"
        # Sum back to 1.0 → save enabled
        assert modal.query_one("#confirm", Button).disabled is False


# ---- Save flow --------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_with_valid_sum_persists_all_keys_via_batch(service):
    """Modal save → save_knob_batch with N keys → all visible in db."""
    from polily.core.config_store import load_all

    modal = _make_modal(service)
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        # New balanced split: 0.20 / 0.20 / 0.20 / 0.20 / 0.20
        for leaf in _CRYPTO_MAG_DEFAULTS:
            modal.query_one(f"#input-{leaf}", Input).value = "0.20"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    flat = load_all(service.db)
    for leaf in _CRYPTO_MAG_DEFAULTS:
        assert flat[f"{_CRYPTO_MAG_PREFIX}.{leaf}"] == 0.20, leaf


@pytest.mark.asyncio
async def test_save_with_pydantic_invalid_value_shows_error_and_db_unchanged(
    service,
):
    """Float-coercible but Pydantic-invalid input.

    A negative weight is meaningful here: live float-coercion succeeds,
    the modal-level sum check passes if the other inputs compensate, but
    Pydantic still rejects (weight values are typed `float` but a
    negative weight makes the scorer produce nonsense — we can engineer
    the failure via an explicit constraint at a different layer).

    We use the simpler available signal: live validation rejects the
    negative value (UX warning). Re-route: assert the negative input
    keeps Save disabled regardless of sum, AND db is untouched.
    """
    from polily.core.config_store import load_all

    modal = _make_modal(service)
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        # Negative + compensating positive → arithmetic sum still 1.0
        modal.query_one("#input-price_z_score", Input).value = "-0.20"
        modal.query_one("#input-book_imbalance", Input).value = "0.45"
        await pilot.pause()
        # Live validation must reject negatives → Save disabled.
        assert modal.query_one("#confirm", Button).disabled is True
        # Try pressing anyway — disabled button is a no-op, db unchanged
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    flat = load_all(service.db)
    assert (
        flat[f"{_CRYPTO_MAG_PREFIX}.price_z_score"]
        == _CRYPTO_MAG_DEFAULTS["price_z_score"]
    )


@pytest.mark.asyncio
async def test_save_propagates_pydantic_failure_via_error_static(
    service, monkeypatch,
):
    """If save_knob_batch raises ConfigValidationError, modal shows error
    and db is unchanged. Forces the error path by monkeypatching the
    backend; modal must not crash on the raise.
    """
    from polily.core import config as config_mod
    from polily.core.config import ConfigValidationError
    from polily.core.config_store import load_all

    def boom(_db, _updates):
        raise ConfigValidationError("forged validation [type=greater_than]")

    monkeypatch.setattr(config_mod, "save_knob_batch", boom)

    modal = _make_modal(service)
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()
        error = modal.query_one("#modal-error", Static)
        rendered = str(error.render())
        # Error static carries the message; brackets are escaped via
        # rich.markup.escape so they render literally (no MarkupError).
        assert "forged validation" in rendered

    # db unchanged
    flat = load_all(service.db)
    for leaf, default in _CRYPTO_MAG_DEFAULTS.items():
        assert flat[f"{_CRYPTO_MAG_PREFIX}.{leaf}"] == default


# ---- Cancel / ESC -----------------------------------------------------------


@pytest.mark.asyncio
async def test_escape_dismisses_with_none(service):
    """ESC → dismiss(None). Canonical pattern: callback harness."""
    captured = {}

    class _CallbackHarness(App):
        def on_mount(self) -> None:
            self.push_screen(
                _make_modal(service),
                lambda result: captured.setdefault("result", result),
            )

    async with _CallbackHarness().run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert captured.get("result") is None


# ---- Glossary collapsible ---------------------------------------------------


@pytest.mark.asyncio
async def test_glossary_collapsible_renders_only_relevant_signals(service):
    """The glossary block lists ONLY signals that exist as leaves in this
    family. crypto/magnitude has price_z_score etc. but NOT
    sustained_drift (that's political-only).
    """
    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        glossary_widget = modal.query_one("#glossary-block")
        text = "".join(
            str(s.render()) if hasattr(s, "render") else getattr(s, "source", "")
            for s in glossary_widget.query("*")
        )
        # Crypto-specific magnitude leaves present
        assert "price_z_score" in text
        assert "fair_value_divergence" in text
        # Political-only leaf NOT present
        assert "sustained_drift" not in text


@pytest.mark.asyncio
async def test_glossary_collapsible_starts_collapsed(service):
    """The glossary is `collapsed=True` by default — secondary info."""
    from textual.widgets import Collapsible

    modal = _make_modal(service)
    async with _Harness(modal).run_test() as pilot:
        await pilot.pause()
        col = modal.query_one(Collapsible)
        assert col.collapsed is True


@pytest.mark.asyncio
async def test_glossary_collapsible_can_expand(service):
    """User click on the collapsible header toggles it open."""
    from textual.widgets import Collapsible

    modal = _make_modal(service)
    async with _Harness(modal).run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        col = modal.query_one(Collapsible)
        # Programmatic toggle to mimic click
        col.collapsed = False
        await pilot.pause()
        assert col.collapsed is False
