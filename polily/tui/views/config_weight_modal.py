"""WeightFamilyEditModal: family-level edit for movement.weights.* leaves.

Round 4 (v0.10.0 TUI Config). Each family — `crypto/magnitude`,
`political/quality`, ... — is a set of 3-5 signal weights that MUST sum
to 1.0 for the movement scorer's algorithmic invariant
(`polily/monitor/scorer.py:43-46`). Editing one leaf at a time silently
breaks that invariant; this modal enforces it on save (Q2: strict —
Save disabled until sum ∈ [0.99, 1.01]).

Replaces the single-leaf `ConfigEditModal` flow inside the weights
subtree. Single-leaf still applies elsewhere (movement.magnitude_threshold
etc.).

Key UX choices:
  - Live sum: green when in range, yellow when not — same color cue as
    `WeightFamilyNode._sum_text`
  - Auto-normalize: scale all inputs to sum=1 (skip if all zero, with a
    warning toast)
  - Reset: revert every input to its Pydantic default (which sums to 1
    by construction)
  - Glossary: collapsed by default; lists only signals that exist in
    THIS family (so crypto/magnitude shows `fair_value_divergence`,
    not `sustained_drift`)
"""
from __future__ import annotations

import contextlib
from typing import Any

from rich.markup import escape as _escape_markup
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: F401
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Markdown, Static

from polily.tui.i18n import current_language, t
from polily.tui.icons import ICON_CONFIG
from polily.tui.widgets.confirm_cancel_bar import ConfirmCancelBar
from polily.tui.widgets.field_row import FieldRow
from polily.tui.widgets.polily_card import PolilyCard

_MODAL_WIDTH = 92
_WEIGHTS_PREFIX = "movement.weights."
# Widest signal name in `_signals_glossary` is `volume_price_confirmation`
# (25 chars). FieldRow's default label width is 10, which causes char-level
# wrap on long signal names like `fair_value_divergence`. Override locally
# so each row stays 1 line tall.
_LABEL_WIDTH = 28

# Sum tolerance window — matches WeightFamilyNode._sum_text (config.py:276).
_SUM_MIN = 0.99
_SUM_MAX = 1.01


class WeightFamilyEditModal(ModalScreen[bool | None]):
    """Edit one (market_type, family) weight family in a single modal.

    Returns True on successful save, None on cancel/ESC.
    """

    DEFAULT_CSS = f"""
    WeightFamilyEditModal {{
        align: center middle;
    }}
    WeightFamilyEditModal #dialog-box {{
        width: {_MODAL_WIDTH};
        height: auto;
        max-height: 90%;
    }}
    WeightFamilyEditModal #dialog-box > PolilyCard {{
        height: auto;
        margin: 0;
    }}
    WeightFamilyEditModal #modal-keypath {{
        color: $text-muted;
    }}
    WeightFamilyEditModal #family-sum {{
        padding: 1 0 0 0;
    }}
    WeightFamilyEditModal #modal-error {{
        color: $error;
        height: auto;
    }}
    WeightFamilyEditModal #modal-warn {{
        height: 1;
    }}
    /* Compact FieldRow vertical spacing — default has padding-bottom 1 which
       adds 5 blank lines for 5 inputs on a 40-line terminal. We rely on
       Input's own border to provide visual separation between rows. */
    WeightFamilyEditModal FieldRow {{
        padding: 0;
    }}
    WeightFamilyEditModal #glossary-block {{
        height: auto;
        max-height: 12;
    }}
    WeightFamilyEditModal #glossary-block Markdown {{
        max-height: 10;
        overflow-y: auto;
    }}
    WeightFamilyEditModal #glossary-block Markdown {{
        height: auto;
    }}
    WeightFamilyEditModal Input {{ width: 12; }}
    /* FieldRow's default label width is 10, which char-wraps long signal
       names like `volume_price_confirmation` (25 chars). Override locally
       so each row stays 1 line tall. text-align:left because right-aligned
       long labels look ragged when widths vary. */
    WeightFamilyEditModal FieldRow .field-row-label {{
        width: {_LABEL_WIDTH};
        text-align: left;
    }}
    WeightFamilyEditModal #button-row {{
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }}
    WeightFamilyEditModal #button-row Button {{
        margin: 0 1;
        min-width: 14;
    }}
    WeightFamilyEditModal ConfirmCancelBar Button {{ min-width: 14; }}
    """

    # priority=True: Input widgets consume escape; without priority the
    # screen-level binding never fires when an Input has focus.
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(
        self,
        *,
        service,
        key_path_prefix: str,
        current_values: dict[str, float],
        default_values: dict[str, float],
    ) -> None:
        # Defense-in-depth: only `movement.weights.<type>.<family>` is allowed.
        if not key_path_prefix.startswith(_WEIGHTS_PREFIX):
            raise ValueError(
                f"WeightFamilyEditModal requires a movement.weights.* prefix, "
                f"got {key_path_prefix!r}",
            )

        # Each `prefix.<leaf>` must be in TERRITORY_A. The TUI never
        # constructs a forged leaf, but a misuse from another caller
        # should fail loud at construction.
        from polily.core.config_store import is_territory_a
        for leaf in current_values:
            full_path = f"{key_path_prefix}.{leaf}"
            if not is_territory_a(full_path):
                raise ValueError(
                    f"{full_path} is not editable (not in TERRITORY_A)",
                )

        super().__init__()
        self._service = service
        self._key_path_prefix = key_path_prefix
        # Snapshot caller-supplied dicts. `_current_values` is reference-only
        # (initial Input value); the live source of truth after mount is
        # whatever the user has typed.
        self._current_values: dict[str, float] = dict(current_values)
        self._default_values: dict[str, float] = dict(default_values)

        # Parse `movement.weights.<market_type>.<family>` for the title.
        # If this raises (mismatched depth), let it surface — caller passed
        # a malformed prefix.
        parts = key_path_prefix.split(".")
        # ['movement', 'weights', '<market_type>', '<family>']
        self._market_type = parts[2] if len(parts) >= 3 else "?"
        self._which = parts[3] if len(parts) >= 4 else "?"

    # ---- Compose ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        title = t(
            "weight_modal.title",
            icon=ICON_CONFIG,
            market_type=self._market_type,
            family=self._which,
        )
        n_leaves = len(self._current_values)

        # VerticalScroll lets the dialog grow to its natural height but
        # gracefully scroll when the glossary is expanded (or terminals are
        # short) so the bottom buttons + sum line remain reachable. Without
        # this the dialog clips at max-height with no scrollbar.
        with VerticalScroll(id="dialog-box"):
            with PolilyCard(title=title):
                yield Static(
                    t(
                        "weight_modal.keypath_label",
                        key_path=self._key_path_prefix,
                        n=n_leaves,
                    ),
                    id="modal-keypath",
                )

                # Glossary collapsible — only signals present in this family.
                # v0.10.1 (Goku R4): skip the Collapsible entirely when there are no
                # glossary entries. Rendering an empty placeholder wastes a row and
                # confuses readers ("why is this here?").
                glossary = self._build_glossary_markdown()
                if glossary:
                    with Collapsible(
                        title=t("weight_modal.glossary_title"),
                        collapsed=True, id="glossary-block",
                    ):
                        yield Markdown(glossary, id="glossary-md")

                # One FieldRow per leaf — preserves dict insertion order
                # which is Pydantic field order (T5.6 lesson).
                for leaf, value in self._current_values.items():
                    helper_default = t(
                        "weight_modal.input_default",
                        default=self._default_values.get(leaf, 0.0),
                    )
                    yield FieldRow(
                        label=leaf,
                        unit="",
                        input_widget=Input(
                            value=str(value), id=f"input-{leaf}",
                        ),
                        helper=helper_default,
                    )

                yield Static(self._sum_text(), id="family-sum")
                yield Static("", id="modal-error")
                yield Static(
                    t("weight_modal.warn_restart"),
                    id="modal-warn",
                )

                # Helper buttons live above the confirm/cancel bar so the
                # primary action is the lowest, easiest target. Horizontal
                # layout (instead of stacked Vertical) saves 3 lines so the
                # whole modal fits a 40-line terminal without scrolling.
                with Horizontal(id="button-row"):
                    yield Button(
                        t("weight_modal.button.auto_normalize"),
                        id="auto-normalize",
                        variant="primary",
                    )
                    yield Button(
                        t("weight_modal.button.reset"),
                        id="reset-btn", variant="warning",
                    )

                yield ConfirmCancelBar(
                    confirm_label=t("weight_modal.button.save"),
                    cancel_label=t("weight_modal.button.cancel"),
                )

    def on_mount(self) -> None:
        # Initial sum/save state in case any default sums to ≠ 1.0 (defensive).
        self._refresh_sum_and_save_state()

    # ---- Glossary helpers ---------------------------------------------------

    def _build_glossary_markdown(self) -> str:
        """Return a single markdown blob with one block per signal in
        this family. Pulls from `_signals_glossary` in movement.md.

        Filtering to "signals present in this family" means crypto/magnitude
        renders price_z_score etc. but not sustained_drift (which is
        political-only). Reuses the orphan glossary section flagged by Whis.
        """
        from polily.core.config_docs._loader import load_signals_glossary
        # Per-language glossary; same compose-time snapshot pattern as
        # ConfigEditModal — F2 mid-modal won't hot-flip, reopen picks it up.
        glossary = load_signals_glossary(current_language())

        blocks: list[str] = []
        for leaf in self._current_values:
            description = glossary.get(leaf)
            if not description:
                continue
            blocks.append(f"### {leaf}\n\n{description}")
        return "\n\n".join(blocks)

    # ---- Sum + Save state ---------------------------------------------------

    def _read_inputs(self) -> dict[str, float]:
        """Read every Input's current value as float. Non-numeric or
        negative values are returned as-is (negative); the live-validate
        path treats them as invalid.
        """
        values: dict[str, float] = {}
        for leaf in self._current_values:
            try:
                widget = self.query_one(f"#input-{leaf}", Input)
            except Exception:
                # Pre-mount path — return seed values
                values[leaf] = float(self._current_values[leaf])
                continue
            try:
                values[leaf] = float(widget.value)
            except (ValueError, TypeError):
                # Sentinel for "not a number" — _sum etc. can't compute
                # but Save remains disabled either way.
                values[leaf] = float("nan")
        return values

    def _current_sum(self) -> float:
        values = self._read_inputs()
        # NaN propagates → sum is NaN → range check fails → Save disabled.
        return sum(values.values())

    def _has_negative_or_invalid(self, values: dict[str, float]) -> bool:
        for v in values.values():
            if v != v:  # NaN check (NaN != NaN)
                return True
            if v < 0:
                return True
        return False

    def _sum_text(self) -> str:
        total = self._current_sum()
        if total != total:  # NaN
            return t("weight_modal.sum.nan")
        in_range = _SUM_MIN <= total <= _SUM_MAX
        color = "green" if in_range else "yellow"
        if in_range:
            return t("weight_modal.sum.in_range", color=color, total=total)
        return t(
            "weight_modal.sum.out_of_range",
            color=color, total=total, lo=_SUM_MIN, hi=_SUM_MAX,
        )

    def _refresh_sum_and_save_state(self) -> None:
        """Re-render the sum static and update Save's disabled flag."""
        with contextlib.suppress(Exception):
            self.query_one("#family-sum", Static).update(self._sum_text())
        with contextlib.suppress(Exception):
            confirm = self.query_one("#confirm", Button)
            values = self._read_inputs()
            total = sum(values.values())
            in_range = (
                total == total
                and _SUM_MIN <= total <= _SUM_MAX
                and not self._has_negative_or_invalid(values)
            )
            confirm.disabled = not in_range

    # ---- Event handlers -----------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:  # noqa: ARG002
        # Refresh on every keystroke. Float conversion is cheap; no need
        # for a CJK IME debounce here because there's no error-static
        # flicker — the sum widget just updates inline.
        self._refresh_sum_and_save_state()
        # Clear any prior backend error message — user is editing again.
        with contextlib.suppress(Exception):
            self.query_one("#modal-error", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "auto-normalize":
            self._do_auto_normalize()
        elif event.button.id == "reset-btn":
            self._do_reset()

    def on_confirm_cancel_bar_confirmed(
        self,
        event: ConfirmCancelBar.Confirmed,  # noqa: ARG002
    ) -> None:
        self._do_save()

    def on_confirm_cancel_bar_cancelled(
        self,
        event: ConfirmCancelBar.Cancelled,  # noqa: ARG002
    ) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ---- Actions ------------------------------------------------------------

    def _do_auto_normalize(self) -> None:
        values = self._read_inputs()
        # If any value is NaN, normalize is meaningless — bail with warning.
        if any(v != v for v in values.values()):
            self.notify(
                t("weight_modal.notify.normalize_nan"),
                severity="warning",
                timeout=4,
            )
            return
        total = sum(values.values())
        if total <= 0:
            self.notify(
                t("weight_modal.notify.normalize_zero"),
                severity="warning",
                timeout=4,
            )
            return
        for leaf, value in values.items():
            scaled = value / total
            with contextlib.suppress(Exception):
                self.query_one(f"#input-{leaf}", Input).value = (
                    f"{scaled:.4f}".rstrip("0").rstrip(".") or "0"
                )
        # Force re-read (Input.Changed will fire too, but be eager).
        self._refresh_sum_and_save_state()

    def _do_reset(self) -> None:
        for leaf, default in self._default_values.items():
            with contextlib.suppress(Exception):
                self.query_one(f"#input-{leaf}", Input).value = str(default)
        # Clear any prior error.
        with contextlib.suppress(Exception):
            self.query_one("#modal-error", Static).update("")
        self._refresh_sum_and_save_state()
        # Defense-in-depth: explicitly re-enable confirm in case
        # `_refresh_sum_and_save_state`'s `contextlib.suppress` swallowed
        # an exception (mirrors ConfigEditModal SF5).
        with contextlib.suppress(Exception):
            self.query_one("#confirm", Button).disabled = False

    def _do_save(self) -> None:
        # Pull the latest input snapshot at save time.
        values = self._read_inputs()
        if self._has_negative_or_invalid(values):
            self._show_error(t("weight_modal.error.must_be_nonneg"))
            return
        total = sum(values.values())
        if not (_SUM_MIN <= total <= _SUM_MAX):
            self._show_error(t(
                "weight_modal.error.sum_out_of_range",
                lo=_SUM_MIN, hi=_SUM_MAX, total=total,
            ))
            return

        # Build the batch update map and commit atomically.
        from polily.core import config as config_mod

        updates: dict[str, Any] = {
            f"{self._key_path_prefix}.{leaf}": values[leaf]
            for leaf in self._current_values
        }
        try:
            config_mod.save_knob_batch(self._service.db, updates)
        except config_mod.ConfigValidationError as e:
            self._show_error(t("weight_modal.error.pydantic_failed", detail=str(e)))
            return
        except (ValueError, Exception) as e:
            # ValueError raised for non-territory-A keys; broader Exception
            # for unforeseen failures. Surface either as a save-time error
            # rather than crashing the modal.
            self._show_error(t("weight_modal.error.save_failed", detail=str(e)))
            return

        self.notify(t(
            "weight_modal.notify.saved",
            key_path_prefix=self._key_path_prefix, n=len(updates),
        ))
        self.dismiss(True)

    def _show_error(self, message: str) -> None:
        # Pydantic ValidationError messages contain `[type=...]` which
        # Static.update interprets as Rich markup → MarkupError. Escape so
        # it renders literally.
        safe = _escape_markup(message) if message else ""
        with contextlib.suppress(Exception):
            self.query_one("#modal-error", Static).update(safe)
