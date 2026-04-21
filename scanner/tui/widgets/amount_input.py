"""v0.8.0 atom: AmountInput — Input specialized for monetary/share amounts.

Provides:
- Numeric validation (must parse as float, must be > 0)
- Optional min_value / max_value bounds
- Emits AmountInput.AmountChanged(value, valid, reason) on every edit
  → value is None when input is empty or unparseable
  → valid is True iff value > 0 AND in [min_value, max_value] (if either set)
  → reason is one of: "empty" | "not_numeric" | "negative" | "below_min"
                      | "above_max" | "ok"

Caller uses @on(AmountInput.AmountChanged) (or the matching
``on_amount_input_amount_changed`` handler name) to react — enable/disable
confirm buttons, update previews, show error hints. The atom itself does
NOT show errors inline; presentation is the caller's job via FieldRow's
helper text or button disabled state.

Inherits Input so existing ``query_one(..., Input)`` call sites keep
working (AmountInput IS-A Input). Reads and writes to ``.value`` stay
identical.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from textual.message import Message
from textual.widgets import Input


class AmountInput(Input):
    """Numeric Input with validation + live valid-state signal."""

    class AmountChanged(Message):
        """Value parsed (or rejected). Emitted on every edit + set_bounds()."""

        def __init__(
            self,
            *,
            input_id: str | None,
            value: float | None,
            valid: bool,
            reason: str = "",
        ) -> None:
            super().__init__()
            self.input_id = input_id
            self.value = value
            self.valid = valid
            self.reason = reason

    def __init__(
        self,
        *,
        id: str | None = None,  # noqa: A002 — Textual widget API convention
        value: str = "",
        placeholder: str = "",
        min_value: float | None = None,
        max_value: float | None = None,
        **kwargs,
    ) -> None:
        # Force type="number" for numeric semantics (restricts keys where
        # the terminal honors it). Caller may still override via kwargs.
        kwargs.setdefault("type", "number")
        super().__init__(
            value=value,
            placeholder=placeholder,
            id=id,
            **kwargs,
        )
        self._min_value = min_value
        self._max_value = max_value

    def set_bounds(
        self,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> None:
        """Update bounds at runtime (e.g. WithdrawModal's max = wallet balance).

        Only the provided kwargs are updated — pass None (the default) to
        leave that bound unchanged. Emits a fresh AmountChanged under the
        new bounds so caller UI re-reacts.
        """
        if min_value is not None:
            self._min_value = min_value
        if max_value is not None:
            self._max_value = max_value
        self._emit_current()

    def parse(self) -> tuple[float | None, bool, str]:
        """Parse current value. Returns (value, valid, reason).

        Uses Decimal for exact parsing (so "0.1" does not subtly reject
        some float-specific edge cases). Returns:
          - (None, False, "empty") if value is whitespace-only
          - (None, False, "not_numeric") if value can't be parsed
          - (v, False, "negative") if v <= 0
          - (v, False, "below_min" | "above_max") if bound violated
          - (v, True, "ok") otherwise
        """
        raw = self.value.strip()
        if not raw:
            return None, False, "empty"
        try:
            val = float(Decimal(raw))
        except (ValueError, InvalidOperation):
            return None, False, "not_numeric"
        if val <= 0:
            return val, False, "negative"
        if self._min_value is not None and val < self._min_value:
            return val, False, "below_min"
        if self._max_value is not None and val > self._max_value:
            return val, False, "above_max"
        return val, True, "ok"

    def _emit_current(self) -> None:
        value, valid, reason = self.parse()
        self.post_message(
            self.AmountChanged(
                input_id=self.id,
                value=value,
                valid=valid,
                reason=reason,
            ),
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Convert the base Input.Changed event into our AmountChanged event.

        We stop the base event so upstream ``on_input_changed`` handlers
        that still expect the legacy protocol won't see it twice. Callers
        should migrate to ``on_amount_input_amount_changed``.
        """
        if event.input is self:
            self._emit_current()
            event.stop()
