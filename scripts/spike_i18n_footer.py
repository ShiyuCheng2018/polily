"""Spike: 验证 Textual 8.x 上 footer 文案能否随语言运行时切换。

对应设计文档: docs/runtime-i18n-design.md §6

运行方式:
    .venv/bin/python scripts/spike_i18n_footer.py rebuild        # 方案 1: rebuild _bindings + refresh_bindings()
    .venv/bin/python scripts/spike_i18n_footer.py custom_footer  # 方案 4: 自定义 Footer

按键说明（全部用 F-key, 避免被 Input 焦点消化掉）:
    f2           切换中英文（关键按键，观察 footer 变化）
    f3           打开 modal（验证 modal 场景）
    在 modal 里:  f2 再切一次（验证 modal 上的 footer 也跟）
    f5           screen-level binding (refresh, no-op)
    f6           screen-level binding (delete, no-op)
    ctrl+s       Input 自己的 binding（焦点在 Input 上才显示在 footer）
    esc          关 modal
    f10          退出

观察点（每种方案分别观察）:
    1. 没焦点时切语言, footer 是否变
    2. 焦点在 Input 上时切语言, footer 是否变（焦点链上的 widget binding）
    3. modal 打开时切语言, footer 是否变
    4. 切回中文再切回英文, 是否累积污染
    5. 切换瞬间是否可见闪烁
"""
from __future__ import annotations

import sys
import threading
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Static


# ============================================================================
# 极简 i18n catalog
# ============================================================================
# Catalog key 命名约定: binding.<action_name> — 让方案 4 的 CustomFooter 能直接用
# t(f"binding.{binding.action}") 查表, 不需要额外的 action→key 映射表。
_CATALOGS: dict[str, dict[str, str]] = {
    "zh": {
        "binding.quit": "退出",
        "binding.toggle_lang": "切换语言",
        "binding.open_modal": "打开弹窗",
        "binding.refresh": "刷新",
        "binding.delete": "删除",
        "binding.dismiss": "关闭",
        "binding.submit": "提交",
        "title.main": "主屏幕",
        "title.modal": "弹窗",
        "label.input_hint": "焦点在我身上时再切语言, 看看 footer 上 ctrl+s (Input 自己的 binding) 是否跟随",
        "label.body": "按 f2 切语言, f3 开 modal, f10 退出.",
    },
    "en": {
        "binding.quit": "Quit",
        "binding.toggle_lang": "Toggle Lang",
        "binding.open_modal": "Open Modal",
        "binding.refresh": "Refresh",
        "binding.delete": "Delete",
        "binding.dismiss": "Close",
        "binding.submit": "Submit",
        "title.main": "Main Screen",
        "title.modal": "Modal",
        "label.input_hint": "Focus me, then toggle lang to verify focus-chain widget bindings refresh too",
        "label.body": "Press f2 to toggle lang, f3 to open modal, f10 to quit.",
    },
}

_lock = threading.RLock()
_current_lang = "zh"


def t(key: str) -> str:
    with _lock:
        cat = _CATALOGS.get(_current_lang, {})
    return cat.get(key, _CATALOGS["zh"].get(key, key))


def toggle_lang() -> str:
    global _current_lang
    with _lock:
        _current_lang = "en" if _current_lang == "zh" else "zh"
        return _current_lang


# ============================================================================
# 方案 1: rebuild _bindings + screen.refresh_bindings()
# ============================================================================

def _make_app_bindings():
    return [
        Binding("f10", "quit", t("binding.quit"), show=True),
        Binding("f2", "toggle_lang", t("binding.toggle_lang"), show=True),
        Binding("f3", "open_modal", t("binding.open_modal"), show=True),
        Binding("f5", "refresh", t("binding.refresh"), show=True),
        Binding("f6", "delete", t("binding.delete"), show=True),
    ]


def _make_screen_bindings():
    # 保留以备将来扩展, 当前 app-level 已经够用
    return []


def _make_modal_bindings():
    return [
        Binding("escape", "dismiss", t("binding.dismiss"), show=True),
        Binding("f2", "toggle_lang", t("binding.toggle_lang"), show=True),
    ]


def _make_input_bindings():
    """Input 子类的 BINDINGS — 验证焦点链上的 widget 也要 rebuild。"""
    return [
        Binding("ctrl+s", "submit", t("binding.submit"), show=True),
    ]


class _RebuildableMixin:
    """挂上 BINDINGS 的节点都用这个 — 提供 _rebuild_bindings()。"""

    def _bindings_factory(self) -> list[Binding]:
        return []

    def rebuild_bindings(self) -> None:
        # 关键: 直接覆盖私有属性 _bindings (textual.dom.DOMNode.__init__ 写过)
        self._bindings = BindingsMap(self._bindings_factory())


class RebuildInput(_RebuildableMixin, Input):
    def _bindings_factory(self):
        return _make_input_bindings()

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rebuild_bindings()


class RebuildModal(_RebuildableMixin, ModalScreen):
    def _bindings_factory(self):
        return _make_modal_bindings()

    def __init__(self):
        super().__init__()
        self.rebuild_bindings()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"[b]{t('title.modal')}[/b]", id="rebuild_modal_title"),
            Static(t("label.body"), id="rebuild_modal_body"),
            Footer(),
        )

    async def action_dismiss(self, result=None) -> None:  # pragma: no cover - manual spike
        self.dismiss()

    async def action_toggle_lang(self) -> None:
        # 走 app 的 action 让重建逻辑统一在一处
        await self.app.action_toggle_lang()


class RebuildScreen(_RebuildableMixin):
    pass


class RebuildApp(_RebuildableMixin, App):
    """方案 1 的 App."""
    TITLE = "Spike: rebuild _bindings"

    BINDINGS: ClassVar = []  # 我们用 _bindings_factory 接管

    def _bindings_factory(self):
        return _make_app_bindings()

    def __init__(self):
        super().__init__()
        self.rebuild_bindings()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"[b]{t('title.main')}[/b]", id="title")
        yield Static(t("label.body"), id="body")
        yield Static(t("label.input_hint"), id="hint")
        yield RebuildInput(placeholder="focus me with Tab")
        yield Footer()

    def action_refresh(self):
        pass

    def action_delete(self):
        pass

    def action_open_modal(self):
        self.push_screen(RebuildModal())

    async def action_toggle_lang(self) -> None:
        toggle_lang()

        # Step 1: 重建 app 自己的 _bindings
        self.rebuild_bindings()

        # Step 2: 重建 screen_stack 上每个 screen 的 _bindings
        # + 每个 screen 子树里有 _bindings_factory 的 widget 的 _bindings
        for screen in self.screen_stack:
            if hasattr(screen, "rebuild_bindings"):
                screen.rebuild_bindings()
            for node in screen.walk_children(with_self=False):
                if hasattr(node, "rebuild_bindings"):
                    node.rebuild_bindings()

        # Step 3: 重建 view 内的可见 Static (description 直接 hardcode 了 t() 旧值)
        # 注意: 真实项目里这一步是各 view 的 _render_all() 走 EventBus
        try:
            self.query_one("#title", Static).update(f"[b]{t('title.main')}[/b]")
            self.query_one("#body", Static).update(t("label.body"))
            self.query_one("#hint", Static).update(t("label.input_hint"))
        except Exception:
            pass
        for screen in self.screen_stack:
            if isinstance(screen, RebuildModal):
                try:
                    screen.query_one("#rebuild_modal_title", Static).update(f"[b]{t('title.modal')}[/b]")
                    screen.query_one("#rebuild_modal_body", Static).update(t("label.body"))
                except Exception:
                    pass

        # Step 4: 触发 Footer recompose
        self.screen.refresh_bindings()
        # screen_stack 上每个 screen 都触发一次 (因为 modal 里也有 Footer)
        for screen in self.screen_stack:
            screen.refresh_bindings()


# ============================================================================
# 方案 4: 自定义 Footer (订阅 i18n 事件, 自己 recompose)
# ============================================================================

# 用 Textual 的 reactive 之外, 简化为模块级 callback list
_footer_subscribers: list = []


def _notify_footers():
    for cb in list(_footer_subscribers):
        try:
            cb()
        except Exception:
            pass


class CustomFooter(Static):
    """简化版 footer: 从 app/screen 当前 active_bindings 读 binding,
    description 通过 t(f"binding.{action}") 约定查表。
    """

    def on_mount(self):
        _footer_subscribers.append(self._on_lang_change)
        self._render_now()

    def on_unmount(self):
        if self._on_lang_change in _footer_subscribers:
            _footer_subscribers.remove(self._on_lang_change)

    def _on_lang_change(self):
        # 注意: 不能直接 update, 必须 hop 到 UI 线程
        # spike 简化: 直接同步 update (假设来自 UI 线程, action 触发就是 UI 线程)
        self._render_now()

    def _render_now(self):
        try:
            screen = self.app.screen
            active = screen.active_bindings
        except Exception:
            return
        parts = []
        for _, binding, enabled, _tooltip in active.values():
            if not binding.show:
                continue
            # 约定: description 从 i18n catalog 现读
            label = t(f"binding.{binding.action}")
            if not label:
                label = binding.description or binding.action
            disabled = "" if enabled else " (disabled)"
            parts.append(f"[reverse] {binding.key} [/reverse] {label}{disabled}")
        self.update("  ".join(parts))


# 方案 4 仍然需要 _bindings 是正确的 (key/action 不变, 不需要 rebuild description)
# 所以方案 4 的 BINDINGS 可以是普通常量


# 注意: 方案 4 里 description 不能用空字符串 — 因为 textual.binding.Binding.make_bindings
# (binding.py:161) 会强行把 show 设为 `bool(description and show)`, 空 description 直接被
# show=False 掉, 导致 Footer 完全看不到这条 binding。
# 解决: 给 description 一个非空占位 (空格), 真实文案由 CustomFooter._render_now 现求 t() 覆盖。
_PLACEHOLDER = " "

CUSTOM_APP_BINDINGS = [
    Binding("f10", "quit", _PLACEHOLDER, show=True),
    Binding("f2", "toggle_lang", _PLACEHOLDER, show=True),
    Binding("f3", "open_modal", _PLACEHOLDER, show=True),
    Binding("f5", "refresh", _PLACEHOLDER, show=True),
    Binding("f6", "delete", _PLACEHOLDER, show=True),
]

CUSTOM_SCREEN_BINDINGS = []

CUSTOM_MODAL_BINDINGS = [
    Binding("escape", "dismiss", _PLACEHOLDER, show=True),
    Binding("f2", "toggle_lang", _PLACEHOLDER, show=True),
]

CUSTOM_INPUT_BINDINGS = [
    Binding("ctrl+s", "submit", _PLACEHOLDER, show=True),
]


class CustomInput(Input):
    BINDINGS = CUSTOM_INPUT_BINDINGS

    def action_submit(self):
        pass


class CustomModal(ModalScreen):
    BINDINGS = CUSTOM_MODAL_BINDINGS

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"[b]{t('title.modal')}[/b]", id="modal_title"),
            Static(t("label.body"), id="modal_body"),
            CustomFooter(id="modal_footer"),
        )

    async def action_dismiss(self, result=None):
        self.dismiss()

    async def action_toggle_lang(self):
        await self.app.action_toggle_lang()


class CustomFooterApp(App):
    TITLE = "Spike: custom Footer"
    BINDINGS = CUSTOM_APP_BINDINGS

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"[b]{t('title.main')}[/b]", id="title")
        yield Static(t("label.body"), id="body")
        yield Static(t("label.input_hint"), id="hint")
        yield CustomInput(placeholder="focus me with Tab")
        yield CustomFooter(id="main_footer")

    def action_refresh(self):
        pass

    def action_delete(self):
        pass

    def action_open_modal(self):
        self.push_screen(CustomModal())

    async def action_toggle_lang(self):
        toggle_lang()
        # 1. 通知所有 CustomFooter recompose
        _notify_footers()
        # 2. view 里的 Static 也得刷 (项目里这一步走 EventBus + view._render_all)
        try:
            self.query_one("#title", Static).update(f"[b]{t('title.main')}[/b]")
            self.query_one("#body", Static).update(t("label.body"))
            self.query_one("#hint", Static).update(t("label.input_hint"))
        except Exception:
            pass
        for screen in self.screen_stack:
            for static in screen.query(Static):
                if static.id == "modal_title":
                    static.update(f"[b]{t('title.modal')}[/b]")
                elif static.id == "modal_body":
                    static.update(t("label.body"))


# ============================================================================
# Entry
# ============================================================================

def main():
    method = sys.argv[1] if len(sys.argv) > 1 else "rebuild"
    if method == "rebuild":
        RebuildApp().run()
    elif method == "custom_footer":
        CustomFooterApp().run()
    else:
        print(f"Unknown method: {method!r}. Use 'rebuild' or 'custom_footer'.")
        sys.exit(2)


if __name__ == "__main__":
    main()
