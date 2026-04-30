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

    SF11 — only count keys present in BOTH snapshots. If the db happens
    to have a key not in `loaded` (hot-upgrade where daemon's PolilyConfig
    schema is newer than TUI's, partial-migration leftovers, manual
    sqlite insert), treat it as "new field, not user edit" rather than
    counting it as ghost drift.
    """
    return sum(
        1 for k in loaded
        if k not in EPHEMERAL_FIELDS
        and k in current
        and current[k] != loaded[k]
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

    def _line1_text(self) -> str:
        """Line-1 markup string. Extracted so update_displayed_value() can
        re-render without re-composing the whole row."""
        if self.is_pending:
            value_str = (
                f"[dim]{self.loaded_value}[/dim] [yellow]→[/yellow] "
                f"[bold]{self.current_value}[/bold]"
            )
        else:
            value_str = f"{self.current_value}"
        return (
            f"  {self.last_segment_label:<32} "
            f"{value_str:>14}   "
            f"[dim]{self.source_label}[/dim]   ⓘ"
        )

    def compose(self) -> ComposeResult:
        # Stable IDs ("line-1") let update_displayed_value() re-render this
        # one Static in place — no recompose, no widget churn.
        yield Static(self._line1_text(), classes="leaf-line-1")
        yield Static(
            f"     {self.key_path}",
            classes="leaf-line-2",
        )

    def update_displayed_value(
        self,
        new_current_value: Any,
        new_loaded_value: Any | None = None,
    ) -> None:
        """B4 — Refresh value display in place after the user saves a knob.

        Called by ConfigView._refresh_state_in_place. Avoids
        refresh(recompose=True), which would wipe section expand state,
        scroll position, and focus.
        """
        self.current_value = new_current_value
        if new_loaded_value is not None:
            self.loaded_value = new_loaded_value
        # The first child Static carries class "leaf-line-1" — update
        # its renderable rather than recomposing the whole widget.
        import contextlib
        with contextlib.suppress(Exception):
            line1 = self.query_one(".leaf-line-1", Static)
            line1.update(self._line1_text())

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
        """SF7 — direct view reference, no parent walk.

        B4: in-place refresh — recompose=True would wipe section expand
        state / scroll position / focus on every save.
        """
        if self._view is None:
            return
        self._view._refresh_state_in_place()


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

    def _sum_text(self) -> str:
        sum_color = "green" if 0.99 <= self.family_sum <= 1.01 else "yellow"
        return (
            f"     [dim]sum = [{sum_color}]{self.family_sum:.2f}[/{sum_color}][/dim]"
        )

    def compose(self) -> ComposeResult:
        yield Static(
            f"   ▼ {self.family}",
            classes="family-header",
        )
        yield Static(self._sum_text(), classes="family-sum")
        yield from self._leaves

    def update_family_sum(self) -> None:
        """B4 — Refresh sum badge in place after a leaf value changes."""
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one(".family-sum", Static).update(self._sum_text())


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
    """One foldable section. Holds a header + list of LeafRow children.

    SF15 — focusable so keyboard-only users can Tab to a section header
    and press Enter/Space to expand/collapse. Without can_focus=True the
    BINDINGS below never fired for keyboard nav (only mouse click via the
    parent's on_click).
    """

    can_focus = True

    DEFAULT_CSS = """
    ConfigSection { height: auto; padding: 1 0; }
    ConfigSection .section-header { color: $primary; text-style: bold; padding: 0 1; }
    ConfigSection .section-body { height: auto; }
    ConfigSection.collapsed .section-body { display: none; }
    ConfigSection:focus {
        background: $primary 20%;
    }
    """

    # SF15 — Space mirrors Enter (a11y convention). show=False keeps the
    # global help bar uncluttered; focus highlight signals discoverability.
    BINDINGS = [
        Binding("enter", "toggle", "展开/折叠", show=False),
        Binding("space", "toggle", "展开/折叠", show=False),
    ]

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

    def _header_text(self) -> str:
        marker = "▼" if self.expanded else "▶"
        badge = ""
        if self._view is not None:
            changed, total = self._count_section_changes()
            badge = f"   [dim][已改 {changed} / {total}][/dim]"
        return f"{marker}  {self.section_title}{badge}"

    def compose(self) -> ComposeResult:
        yield Static(
            self._header_text(),
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

        Round-2 (Whis #2) — Skip keys present in `current_config` but missing
        from `default_config`. Twin of SF11's drift-counter fix: if db has a
        stale row (future schema rename / partial migration / manual sqlite
        insert), we don't know what its "default" should be, so it's neither
        a user edit nor a default — exclude it entirely. Without this guard,
        `view.default_config[k]` raises KeyError and crashes the section
        header re-render → kills the whole config view mount.
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
            if k not in view.default_config:
                # Stale row — not a current schema field. Skip cleanly.
                continue
            total += 1
            if v != view.default_config[k]:
                changed += 1
        return changed, total

    def update_count_badge(self) -> None:
        """B4 — Refresh the section header [已改 N/M] badge in place after
        a save. Updates only the header Static, leaving body / leaves /
        weights tree intact (so expand state, scroll, focus all survive).
        """
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one(f"#header-{self.section_id}", Static).update(
                self._header_text(),
            )

    def action_toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")
        # Marker (▶/▼) lives in the header Static — update in place
        # rather than recomposing the entire section (which would
        # rebuild every LeafRow + WeightsTree under it).
        self.update_count_badge()


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
        # Round-2 (Whis #3) — Guard against rapid Ctrl+R double-tap spawning
        # two concurrent `polily scheduler restart` subprocesses. SF17's
        # `exclusive=True` only cancels the prior worker's coroutine wrapper;
        # a thread-mode worker already blocking inside subprocess.run cannot
        # be cancelled at the OS level, so without this guard worker B's
        # thread launches a second subprocess.
        self._restart_in_flight = False

    def _refresh_state(self) -> None:
        """Snapshot the 3 dicts: defaults, loaded (TUI startup snapshot), current (latest db).

        SF11 — `current_config` is the db state directly, not merged with
        `loaded_config`. ensure_seeded runs at startup so db always has
        the full territory-A set; merging would only matter if db were
        somehow incomplete, in which case we'd want to surface that as
        "missing key" rather than silently fall back to the stale loaded
        value. The drift-count helper filters keys-only-in-db separately.
        """
        from polily.core.config import PolilyConfig
        from polily.core.config_store import load_all
        self.default_config = _flatten_pydantic(PolilyConfig())
        self.loaded_config = _flatten_pydantic(self.service.config)
        try:
            self.current_config = load_all(self.service.db)
        except Exception:
            # Defensive: if db read fails entirely, fall back to loaded
            # snapshot so the view still renders rather than crashing.
            self.current_config = dict(self.loaded_config)

    def compose(self) -> ComposeResult:
        yield Static(
            self._banner_text(),
            id="drift-banner",
            classes="banner",
        )
        # SF16 — Previously the PolilyCard was yielded as a sibling of
        # the VerticalScroll with no children mounted into it, producing
        # a stray bordered "配置" card with empty body that ate vertical
        # space. Wrap the scroll inside so the title labels the scroll
        # region (matches wallet.py:135-137 pattern).
        with PolilyCard(title=f"{ICON_CONFIG} 配置", id="config-card"):
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

    def _refresh_drift_banner(self) -> None:
        """Re-render the drift banner Static in place."""
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one("#drift-banner", Static).update(self._banner_text())

    def _refresh_state_in_place(self) -> None:
        """Re-read db.config and push new values into the existing widget tree.

        Replacement for `refresh(recompose=True)` which would wipe section
        expand/collapse state, scroll position, and focus — the #1 UX
        defect users hit when the modal closes after a save (B4).

        Order of updates:
          1. snapshot dicts (defaults / loaded / current)
          2. each LeafRow gets its current_value + line-1 Static refreshed
          3. each WeightFamilyNode resyncs its sum badge (depends on leaf
             values)
          4. each ConfigSection re-renders its [已改 N/M] header badge
          5. drift banner re-renders

        Round-2 (Goku #1) — schema-shape changes mid-session are NOT
        handled. This method only updates EXISTING LeafRow /
        WeightFamilyNode / ConfigSection widgets. If a future feature
        (live schema migration, plugin architecture) adds or removes
        leaves while the view is open, that will require a full
        recompose path. v0.10.0 freezes the schema at PolilyConfig
        import time, so this is fine — flagged for v0.11.0+ consideration.
        """
        self._refresh_state()

        for leaf_row in self.query(LeafRow):
            new_current = self.current_config.get(leaf_row.key_path)
            new_loaded = self.loaded_config.get(leaf_row.key_path)
            if new_current is None:
                # Defensive: leaf disappeared from config (shouldn't happen
                # after T5.x but skip rather than crash).
                continue
            leaf_row.update_displayed_value(new_current, new_loaded)

        for family in self.query(WeightFamilyNode):
            family.update_family_sum()

        for section in self.query(ConfigSection):
            section.update_count_badge()

        self._refresh_drift_banner()

    def action_refresh(self) -> None:
        # In-place refresh preserves expand/collapse state, scroll, and
        # focus — the user pressed `r`, they don't expect their reading
        # context to disappear.
        self._refresh_state_in_place()

    def action_restart_polily(self) -> None:
        """Restart polily so config changes take effect.

        Per design §5.5.2 + Whis B1:
          1. Regenerate yaml so disk mirror is current (fast — main thread)
          2. Delegate to `polily scheduler restart` on a WORKER THREAD
             (SF17) — handles unload + kill + ensure_daemon_running with
             the correct sequence that v0.9.0 established. Avoids bare
             kill_daemon(TERM) which would trigger launchd crash loop
             due to KeepAlive=true.
          3. On success: notify user + 2s delay + os._exit(0).
             On failure (rc != 0 or subprocess raises): surface error
             via notify and DO NOT exit (SF4) — otherwise the TUI
             silently dies while the daemon stays dead, and the user
             reopens 30s later to find no daemon running with no clue
             why.

        SF17 — subprocess runs on a worker thread so a hung restart (up
        to 10s timeout) doesn't freeze the event loop. UI updates from
        the worker go via `app.call_from_thread`. Mirrors the
        WalletResetModal pattern (wallet_modals.py:347-389).

        Round-2 (Whis #3) — `_restart_in_flight` short-circuits a rapid
        second invocation. SF17's `exclusive=True` cancels the prior
        worker's wrapper, but a thread already inside subprocess.run
        cannot be interrupted at the OS level — without this guard,
        worker B's thread fires a second subprocess.
        """
        import contextlib
        from pathlib import Path

        from polily.core.config_yaml import generate_yaml

        if self._restart_in_flight:
            self.notify(
                "正在重启 daemon — 请稍候",
                severity="warning",
                timeout=3,
            )
            return
        self._restart_in_flight = True

        # Step 1: regenerate yaml so disk reflects current db state.
        # best-effort — yaml is a snapshot, not load-bearing. Fast,
        # safe to run on the main thread.
        with contextlib.suppress(Exception):
            generate_yaml(self.service.config, Path("config.yaml"))

        # Step 2 + 3: subprocess + UI follow-up run on a worker thread so
        # the event loop stays responsive even if `polily scheduler
        # restart` hangs.
        self.notify("正在重启 daemon...", title="重启 polily", timeout=10)
        self.run_worker(self._restart_daemon_worker, thread=True, exclusive=True)

    def _restart_daemon_worker(self) -> None:
        """SF17 — Worker thread body. Runs subprocess, dispatches UI
        updates via app.call_from_thread.

        Round-2 (Whis #3) — `_restart_in_flight` is cleared in `finally`
        via call_from_thread so the guard always lifts even on subprocess
        exception / non-zero rc. Note: on the success path we set_timer
        to os._exit(0) — the flag's lifetime past that point is moot
        (process is dying), but we still clear it for symmetry / test
        determinism.
        """
        import os
        import shutil
        import subprocess
        import sys

        try:
            polily_cmd = shutil.which("polily") or (
                sys.argv[0] if sys.argv else "polily"
            )
            try:
                result = subprocess.run(
                    [polily_cmd, "scheduler", "restart"],
                    capture_output=True,
                    timeout=10,
                    text=True,
                )
            except (
                subprocess.TimeoutExpired, FileNotFoundError, PermissionError,
            ) as e:
                self.app.call_from_thread(
                    self.notify,
                    f"❌ 重启 daemon 失败: {type(e).__name__}: {e}",
                    severity="error",
                    timeout=10,
                )
                return

            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()[:500]
                self.app.call_from_thread(
                    self.notify,
                    f"❌ 重启 daemon 失败 (rc={result.returncode}): "
                    f"{err or '(no output)'}",
                    severity="error",
                    timeout=10,
                )
                return

            # Success — notify + 2s grace + os._exit(0). Both notify and
            # set_timer are main-thread-only Textual APIs.
            self.app.call_from_thread(
                self.notify,
                "✅ Daemon 已重启。polily TUI 将在 2 秒后关闭，请重开。",
                title="重启 polily",
                timeout=2,
            )
            self.app.call_from_thread(
                self.set_timer, 2.0, lambda: os._exit(0),
            )
        finally:
            # Lift the in-flight guard so user can retry (or, on success,
            # for symmetry — the os._exit will fire shortly).
            self.app.call_from_thread(
                setattr, self, "_restart_in_flight", False,
            )

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
        Re-read db, recompute banner.

        SF12 — skip refresh while a modal is on top. screen_stack lists
        screens bottom-to-top; len > 1 means a modal was pushed above the
        main screen (which is where ConfigView is mounted). No point
        refreshing a hidden view, and avoids any subtle stale-snapshot
        race during the modal's save → ConfigView dismiss-callback flow.

        Round-2 (Goku #3) — this skip applies to ANY modal, not just
        ConfigEditModal. If a future feature adds global toast / dialog
        screens that don't hide ConfigView's data, revisit this check —
        today, every modal in polily covers the full screen, so refresh-
        while-hidden is always wasted work, and the broad guard is correct.
        """
        import contextlib

        from polily.tui._dispatch import dispatch_to_ui

        with contextlib.suppress(Exception):
            if len(self.app.screen_stack) > 1:
                return
        with contextlib.suppress(Exception):
            dispatch_to_ui(self.app, self._refresh_and_redraw)

    def _refresh_and_redraw(self) -> None:
        # B4: heartbeat-driven repaint also goes through the in-place
        # path — daemon writes to db every 30s, we don't want to nuke
        # the user's expand/scroll/focus state every tick.
        self._refresh_state_in_place()
