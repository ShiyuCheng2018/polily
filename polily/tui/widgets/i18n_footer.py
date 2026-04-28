"""I18nFooter — Textual Footer subclass that translates binding labels at compose time.

Selected approach (see docs/runtime-i18n-design.md §6.4 / §6.7):
override `compose()` to look up each binding's description via
`t(f"binding.{action}")` instead of reading the frozen
`binding.description` attribute. Subscribe to `TOPIC_LANGUAGE_CHANGED`
so the footer recomposes when the user toggles language.

Coupling note: this widget mirrors the parent's compose() body
(textual/widgets/_footer.py:266-328 in textual 8.2.4). When upgrading
Textual, diff that method against this override and re-sync.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import groupby

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.widgets._footer import FooterKey, FooterLabel, KeyGroup

from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
from polily.tui.i18n import t


def resolve_description(action: str, fallback: str) -> str:
    """Translate `action` via `t(f"binding.{action}")`. Fall back to `fallback`
    if the catalog has no entry (i.e. t() returns the key string)."""
    if not action:
        return fallback
    key = f"binding.{action}"
    translated = t(key)
    if translated == key:
        return fallback
    return translated


class I18nFooter(Footer):
    """Drop-in replacement for `textual.widgets.Footer` that re-translates
    binding labels every time the active language changes.

    Bus topic: `TOPIC_LANGUAGE_CHANGED` triggers a recompose. We use
    `self.call_after_refresh(self.recompose)` (mirrors the parent's
    `bindings_changed` path) so the recompose runs in this widget's own
    message-pump context — required for `FooterKey(...).data_bind(...)`
    to resolve the right reactive owner. `post_message` is thread-safe,
    so the bus handler can run on any thread.
    """

    def on_mount(self) -> None:
        super().on_mount()
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        super().on_unmount()
        get_event_bus().unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        if self.is_attached:
            self.call_after_refresh(self.recompose)

    # NOTE: This is a near-verbatim copy of textual.widgets._footer.Footer.compose
    # (textual 8.2.4, _footer.py:266-328). Only the `binding.description` reads
    # are replaced with `resolve_description(binding.action, binding.description)`
    # so each label flows through the i18n catalog. Keep this in sync on
    # textual upgrades — diff the parent compose first.
    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        active_bindings = self.screen.active_bindings
        bindings = [
            (binding, enabled, tooltip)
            for (_, binding, enabled, tooltip) in active_bindings.values()
            if binding.show
        ]
        action_to_bindings: defaultdict[str, list[tuple[Binding, bool, str]]] = defaultdict(list)
        for binding, enabled, tooltip in bindings:
            action_to_bindings[binding.action].append((binding, enabled, tooltip))

        self.styles.grid_size_columns = len(action_to_bindings)

        # NOTE on compact: parent Footer.compose chains
        #   `.data_bind(compact=Footer.compact)`
        # on each FooterKey to propagate Footer's `compact` reactive (default
        # False) into the child. We can't use data_bind here — it raises
        # `ReactiveError: Footer is not defined on PolilyApp` because Textual's
        # `data_bind` reads `active_message_pump.get()` and binds via
        # `reactive.owner == Footer`, which fails the subclass-vs-PolilyApp
        # check in some recompose paths. Without that propagation, FooterKey's
        # own `compact = reactive(True)` default kicks in — which collapses
        # the description's right padding and produces "Top-upw Withdrawr"
        # crash-together rendering. Fix: explicitly assign `key.compact =
        # False` after construction so each FooterKey lands in the same
        # non-compact CSS branch the unmodified Footer renders.
        def _make_key(*args, **kwargs):
            key = FooterKey(*args, **kwargs)
            key.compact = False
            return key

        for group, multi_bindings_iterable in groupby(
            action_to_bindings.values(),
            lambda multi_bindings_: multi_bindings_[0][0].group,
        ):
            multi_bindings = list(multi_bindings_iterable)
            if group is not None and len(multi_bindings) > 1:
                with KeyGroup(classes="-compact" if group.compact else ""):
                    for multi in multi_bindings:
                        binding, enabled, tooltip = multi[0]
                        description = resolve_description(binding.action, binding.description)
                        yield _make_key(
                            binding.key,
                            self.app.get_key_display(binding),
                            "",
                            binding.action,
                            disabled=not enabled,
                            tooltip=tooltip or description,
                            classes="-grouped",
                        )
                yield FooterLabel(group.description)
            else:
                for multi in multi_bindings:
                    binding, enabled, tooltip = multi[0]
                    description = resolve_description(binding.action, binding.description)
                    yield _make_key(
                        binding.key,
                        self.app.get_key_display(binding),
                        description,
                        binding.action,
                        disabled=not enabled,
                        tooltip=tooltip,
                    )
        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            try:
                _node, binding, enabled, tooltip = active_bindings[
                    self.app.COMMAND_PALETTE_BINDING
                ]
            except KeyError:
                pass
            else:
                description = resolve_description(binding.action, binding.description)
                yield _make_key(
                    binding.key,
                    self.app.get_key_display(binding),
                    description,
                    binding.action,
                    classes="-command-palette",
                    disabled=not enabled,
                    tooltip=binding.tooltip or description,
                )
