"""ConfigView: sidebar entry "⚙ 配置" — TUI knob editor.

Per design §5.2 + Q7. Layout:
  - Banner at top (drift count + "重启 polily" button) — Phase 5.7
  - 4 sections (Movement / Scoring / Mispricing / Wallet), each foldable
  - Inside each section: 2-line leaf rows (last_segment / dim full key_path)
  - Movement section has a nested weights subtree (4 market types ×
    magnitude/quality × N signals)

Edit interaction (modal) is Phase 6.
"""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from polily.core.config_store import EPHEMERAL_FIELDS, _flatten_pydantic, is_territory_a
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.icons import ICON_CONFIG
from polily.tui.service import PolilyService
from polily.tui.widgets.polily_card import PolilyCard

# `EPHEMERAL_FIELDS` is re-exported here so future T5.x leaf-tree code can
# defensively skip ephemerals without re-importing from config_store. The
# `is_territory_a` helper already filters them, so this import is currently
# unused in this module — keep it for symmetry with the plan + downstream use.
_ = EPHEMERAL_FIELDS  # noqa: F401


def _count_pending_changes(loaded: dict, current: dict) -> int:
    """Count knobs whose db value differs from the snapshot TUI loaded
    at startup. Filters EPHEMERAL_FIELDS (api.user_agent never persists).

    Per design §5.5.1 — equivalent to comparing db to yaml on disk
    (yaml = mirror of loaded snapshot at startup). In-memory comparison
    is cheaper than re-reading + parsing yaml each refresh.
    """
    return sum(
        1 for k in current
        if k not in EPHEMERAL_FIELDS and current.get(k) != loaded.get(k)
    )


class LeafRow(Widget):
    """A single config leaf — 2-line layout per Q7.

    Line 1:  <last_segment>      <value>   <source-tag>   ⓘ
    Line 2 (dim small):  <full key_path>

    B3: focusable so keyboard-only users can Tab to it and press Enter to
    open the edit modal. Mouse click still works via on_click.
    """

    # B3 — Tab navigation reaches each leaf; Enter opens the edit modal.
    can_focus = True

    BINDINGS = [
        # show=False keeps the global help bar uncluttered. The ConfigView's
        # parent BINDINGS surface the relevant keys; per-row Enter is
        # discoverable from the focus highlight.
        Binding("enter", "edit", "编辑", show=False),
    ]

    DEFAULT_CSS = """
    LeafRow { height: 2; padding: 0 1; }
    LeafRow .leaf-line-1 { color: $text; }
    LeafRow .leaf-line-2 { color: $text-muted; padding-left: 2; }
    LeafRow .leaf-changed-marker { color: $warning; }
    LeafRow .leaf-source { color: $text-muted; }
    LeafRow:focus {
        background: $primary 30%;
    }
    LeafRow:focus-within {
        background: $primary 30%;
    }
    """

    def __init__(
        self,
        key_path: str,
        current_value: Any,
        loaded_value: Any,
        default_value: Any,
        view: ConfigView | None = None,
    ) -> None:
        super().__init__()
        self.key_path = key_path
        self.current_value = current_value
        self.loaded_value = loaded_value
        self.default_value = default_value
        self._view = view  # SF7 — used by on_click + _on_modal_closed

    @property
    def last_segment_label(self) -> str:
        return self.key_path.rsplit(".", 1)[-1]

    @property
    def is_user_edited(self) -> bool:
        """User edited this leaf if current_value != Pydantic default."""
        return self.current_value != self.default_value

    @property
    def source_label(self) -> str:
        return "你" if self.is_user_edited else "默认"

    @property
    def is_pending(self) -> bool:
        """User edited it AND polily hasn't loaded the new value yet."""
        return self.current_value != self.loaded_value

    def compose(self) -> ComposeResult:
        # Line 1: leaf name + value (with → if pending) + source + info icon
        if self.is_pending:
            value_str = (
                f"[dim]{self.loaded_value}[/dim] [yellow]→[/yellow] "
                f"[bold]{self.current_value}[/bold]"
            )
        else:
            value_str = f"{self.current_value}"

        line1 = (
            f"  {self.last_segment_label:<32} "
            f"{value_str:>14}   "
            f"[dim]{self.source_label}[/dim]   ⓘ"
        )
        yield Static(line1, classes="leaf-line-1")
        yield Static(
            f"     {self.key_path}",
            classes="leaf-line-2",
        )

    def on_click(self) -> None:
        self._open_modal()

    def action_edit(self) -> None:
        """B3 — Enter binding handler. Same flow as mouse click."""
        self._open_modal()

    def _open_modal(self) -> None:
        if self._view is None:
            return
        from polily.tui.views.config_modals import ConfigEditModal
        try:
            modal = ConfigEditModal(
                service=self._view.service,
                key_path=self.key_path,
                current_value=self.current_value,
                default_value=self.default_value,
            )
        except ValueError:
            # T6.7 reject (HIDDEN_IN_TUI / EPHEMERAL) — UI shouldn't have
            # rendered this row in the first place, but defensive no-op.
            return
        self.app.push_screen(modal, self._on_modal_closed)

    def _on_modal_closed(self, result) -> None:
        """SF7 — direct view reference, no parent walk."""
        if self._view is None:
            return
        self._view._refresh_state()
        self._view.refresh(recompose=True)


def _leaves_under_section(
    section_id: str,
    current: dict,
    loaded: dict,
    defaults: dict,
    view: ConfigView | None = None,
) -> list[LeafRow]:
    """Build LeafRow list for one section.

    Filters to territory A only via is_territory_a (Whis SF4 — single source).
    HIDDEN_IN_TUI / EPHEMERAL_FIELDS are auto-excluded by that helper.
    Movement scalar (5) come first; weights subtree comes from T5.8.
    """
    section_prefixes = {
        "movement": "movement.",
        "scoring": "scoring.thresholds.",
        "mispricing": "mispricing.",
        "wallet": "wallet.",
    }
    prefix = section_prefixes[section_id]
    rows: list[LeafRow] = []
    # Iterate in `defaults` order — that's the Pydantic model field-declaration
    # order from `_flatten_pydantic`, which is what users (and the design doc
    # examples) expect to see. Sorting alphabetically would scramble the
    # logical grouping of related knobs.
    # Exclude movement.weights.* from the flat list — weights get their own
    # tree widget in T5.8.
    for key in defaults.keys():
        if not key.startswith(prefix):
            continue
        if not is_territory_a(key):
            continue
        if section_id == "movement" and key.startswith("movement.weights."):
            continue  # weights tree handled separately
        if key not in current:
            continue  # defensive: should not happen since current ⊇ defaults
        rows.append(LeafRow(
            key_path=key,
            current_value=current[key],
            loaded_value=loaded.get(key, defaults.get(key)),
            default_value=defaults[key],
            view=view,
        ))
    return rows


class WeightFamilyNode(Widget):
    """Container for one family (magnitude or quality) of a market type."""

    DEFAULT_CSS = """
    WeightFamilyNode { height: auto; padding: 0 0 0 4; }
    WeightFamilyNode .family-header { color: $primary; }
    WeightFamilyNode .family-sum { color: $text-muted; padding-left: 2; }
    """

    def __init__(
        self,
        market_type: str,
        family: str,
        leaves: list[LeafRow],
    ) -> None:
        super().__init__(id=f"weights-{market_type}-{family}")
        self.market_type = market_type
        self.family = family
        self._leaves = leaves

    @property
    def family_sum(self) -> float:
        return sum(leaf.current_value for leaf in self._leaves)

    def compose(self) -> ComposeResult:
        sum_color = "green" if 0.99 <= self.family_sum <= 1.01 else "yellow"
        yield Static(
            f"   ▼ {self.family}",
            classes="family-header",
        )
        yield Static(
            f"     [dim]sum = [{sum_color}]{self.family_sum:.2f}[/{sum_color}][/dim]",
            classes="family-sum",
        )
        yield from self._leaves


class MarketTypeNode(Widget):
    """Container for one market type (crypto / political / economic_data / default)."""

    DEFAULT_CSS = """
    MarketTypeNode { height: auto; padding: 0 0 0 2; }
    MarketTypeNode .market-type-header { color: $primary; }
    """

    def __init__(
        self,
        market_type: str,
        current: dict,
        loaded: dict,
        defaults: dict,
        view: ConfigView | None = None,
    ) -> None:
        super().__init__()
        self.market_type = market_type
        self._current = current
        self._loaded = loaded
        self._defaults = defaults
        self._view = view

    def compose(self) -> ComposeResult:
        yield Static(
            f"  ▼ {self.market_type}",
            classes="market-type-header",
        )
        for family in ("magnitude", "quality"):
            prefix = f"movement.weights.{self.market_type}.{family}."
            family_leaves: list[LeafRow] = []
            # Iterate defaults to preserve declaration order (T5.6 lesson)
            for k in self._defaults:
                if k.startswith(prefix):
                    family_leaves.append(LeafRow(
                        key_path=k,
                        current_value=self._current[k],
                        loaded_value=self._loaded.get(k, self._defaults.get(k)),
                        default_value=self._defaults[k],
                        view=self._view,
                    ))
            if family_leaves:
                yield WeightFamilyNode(self.market_type, family, family_leaves)


class WeightsTree(Widget):
    """Top-level weights subtree under the Movement section."""

    DEFAULT_CSS = """
    WeightsTree { height: auto; padding: 1 0 0 2; }
    WeightsTree .weights-header { color: $primary; text-style: bold; }
    """

    def __init__(
        self,
        current: dict,
        loaded: dict,
        defaults: dict,
        view: ConfigView | None = None,
    ) -> None:
        super().__init__(id="movement-weights-tree")
        self._current = current
        self._loaded = loaded
        self._defaults = defaults
        self._view = view

    def compose(self) -> ComposeResult:
        yield Static("  ▼ weights (异动信号权重)", classes="weights-header")
        for market_type in ("crypto", "political", "economic_data", "default"):
            yield MarketTypeNode(
                market_type, self._current, self._loaded, self._defaults,
                view=self._view,
            )


class ConfigSection(Widget):
    """One foldable section. Holds a header + list of LeafRow children."""

    DEFAULT_CSS = """
    ConfigSection { height: auto; padding: 1 0; }
    ConfigSection .section-header { color: $primary; text-style: bold; padding: 0 1; }
    ConfigSection .section-body { height: auto; }
    ConfigSection.collapsed .section-body { display: none; }
    """

    BINDINGS = [Binding("enter", "toggle", show=False)]

    def __init__(
        self,
        section_id: str,
        title: str,
        *,
        view: ConfigView | None = None,
        expanded: bool = False,
    ) -> None:
        super().__init__()
        self.section_id = section_id
        self.section_title = title
        self.expanded = expanded
        self._view = view  # SF7 — injected reference for LeafRow click handling later

    def compose(self) -> ComposeResult:
        marker = "▼" if self.expanded else "▶"
        badge = ""
        if self._view is not None:
            changed, total = self._count_section_changes()
            badge = f"   [dim][已改 {changed} / {total}][/dim]"
        yield Static(
            f"{marker}  {self.section_title}{badge}",
            classes="section-header",
            id=f"header-{self.section_id}",
        )
        # Build LeafRow children inline (passed to body Widget's constructor
        # via *children) — avoids the on_mount lazy-mount race where the
        # body Widget yielded in compose() may not exist yet when on_mount
        # runs against the still-composing tree.
        children: list[Widget] = list(self._build_rows())
        if self.section_id == "movement" and self._view is not None:
            children.append(WeightsTree(
                self._view.current_config,
                self._view.loaded_config,
                self._view.default_config,
                view=self._view,
            ))
        yield Widget(
            *children,
            classes="section-body",
            id=f"body-{self.section_id}",
        )

    def _build_rows(self) -> list[LeafRow]:
        if self._view is None:
            return []
        return _leaves_under_section(
            self.section_id,
            self._view.current_config,
            self._view.loaded_config,
            self._view.default_config,
            view=self._view,
        )

    def _count_section_changes(self) -> tuple[int, int]:
        """Count (user_edited, total) leaves under this section's prefix.

        EPHEMERAL_FIELDS excluded. user_edited = current_value != Pydantic default.
        """
        section_prefixes = {
            "movement": "movement.",
            "scoring": "scoring.thresholds.",
            "mispricing": "mispricing.",
            "wallet": "wallet.",
        }
        prefix = section_prefixes[self.section_id]
        view = self._view
        assert view is not None  # guarded at compose-call site
        total = 0
        changed = 0
        for k, v in view.current_config.items():
            if not k.startswith(prefix):
                continue
            if k in EPHEMERAL_FIELDS:
                continue
            total += 1
            if v != view.default_config[k]:
                changed += 1
        return changed, total

    def action_toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")
        self.refresh(recompose=True)


class ConfigView(Widget):
    """Top-level config view widget."""

    DEFAULT_CSS = """
    ConfigView { height: 1fr; padding: 1 2; }
    ConfigView #drift-banner { height: 1; padding: 0 1; margin-bottom: 1; }
    ConfigView #drift-banner.hidden { display: none; }
    ConfigView #config-scroll { height: 1fr; }
    """

    BINDINGS = [
        Binding("r", "refresh", "刷新", show=True),
        Binding("ctrl+r", "restart_polily", "重启 polily", show=True),
        *NAV_BINDINGS,
    ]

    def __init__(self, service: PolilyService) -> None:
        super().__init__()
        self.service = service
        self._refresh_state()

    def _refresh_state(self) -> None:
        """Snapshot the 3 dicts: defaults, loaded (TUI startup snapshot), current (latest db)."""
        from polily.core.config import PolilyConfig
        from polily.core.config_store import load_all
        self.default_config = _flatten_pydantic(PolilyConfig())
        self.loaded_config = _flatten_pydantic(self.service.config)
        try:
            db_flat = load_all(self.service.db)
        except Exception:
            db_flat = {}
        # Merge: db edits win over loaded snapshot. EPHEMERAL_FIELDS
        # already filtered by load_all.
        merged = dict(self.loaded_config)
        merged.update(db_flat)
        self.current_config = merged

    def compose(self) -> ComposeResult:
        yield Static(
            self._banner_text(),
            id="drift-banner",
            classes="banner",
        )
        yield PolilyCard(
            title=f"{ICON_CONFIG} 配置",
            id="config-card",
        )
        with VerticalScroll(id="config-scroll"):
            yield ConfigSection("movement", "异动触发 (Movement)", view=self, expanded=True)
            yield ConfigSection("scoring", "评分 (Scoring)", view=self)
            yield ConfigSection("mispricing", "错误定价 (Mispricing)", view=self)
            yield ConfigSection("wallet", "钱包 (Wallet)", view=self)

    def _banner_text(self) -> str:
        n = _count_pending_changes(self.loaded_config, self.current_config)
        if n == 0:
            return "[dim]无未生效改动[/dim]"
        return (
            f"[yellow]●[/yellow] [bold]{n} 项改动未生效[/bold]   "
            f"[dim](按 Ctrl+R 重启 polily 应用)[/dim]"
        )

    def action_refresh(self) -> None:
        self._refresh_state()
        self.refresh(recompose=True)

    def action_restart_polily(self) -> None:
        """Restart polily so config changes take effect.

        Per design §5.5.2 + Whis B1:
          1. Regenerate yaml so disk mirror is current
          2. Delegate to `polily scheduler restart` (existing CLI command)
             — handles unload + kill + ensure_daemon_running with the
             correct sequence that v0.9.0 established. Avoids bare
             kill_daemon(TERM) which would trigger launchd crash loop
             due to KeepAlive=true.
          3. Notify user + 2s delay + os._exit(0). User re-runs `polily`.

        We do NOT directly call ensure_daemon_running ourselves — the
        scheduler restart subcommand is the canonical path and is already
        tested + maintained.
        """
        import contextlib
        import os
        import subprocess
        import sys
        from pathlib import Path

        from polily.core.config_yaml import generate_yaml

        # Step 1: regenerate yaml so disk reflects current db state.
        # best-effort — yaml is a snapshot, not load-bearing.
        with contextlib.suppress(Exception):
            generate_yaml(self.service.config, Path("config.yaml"))

        # Step 2: delegate to canonical `polily scheduler restart` command.
        # if scheduler restart fails, we still exit TUI.
        with contextlib.suppress(Exception):
            polily_cmd = sys.argv[0] if sys.argv else "polily"
            subprocess.run(
                [polily_cmd, "scheduler", "restart"],
                capture_output=True,
                timeout=10,
            )

        # Step 3: notify user + small delay + exit TUI
        self.notify(
            "polily 已关闭。请重新运行 `polily` 应用改动。",
            title="重启 polily",
        )
        self.set_timer(2.0, lambda: os._exit(0))

    def on_mount(self) -> None:
        from polily.core.events import TOPIC_HEARTBEAT
        self.service.event_bus.subscribe(TOPIC_HEARTBEAT, self._on_heartbeat)

    def on_unmount(self) -> None:
        import contextlib

        from polily.core.events import TOPIC_HEARTBEAT
        with contextlib.suppress(Exception):
            self.service.event_bus.unsubscribe(
                TOPIC_HEARTBEAT, self._on_heartbeat,
            )

    def _on_heartbeat(self, payload: dict) -> None:
        """SF10 — dedicated heartbeat topic, no business-topic hijacking.
        Re-read db, recompute banner."""
        import contextlib

        from polily.tui._dispatch import dispatch_to_ui
        with contextlib.suppress(Exception):
            dispatch_to_ui(self.app, self._refresh_and_redraw)

    def _refresh_and_redraw(self) -> None:
        self._refresh_state()
        self.refresh(recompose=True)
