"""v0.8.0 Q11 key binding spec — centralized constants.

Global bindings (App level):
  q              quit
  ?              show help overlay
  escape         back / cancel / pop screen
  ctrl+p         command palette (includes theme switcher) — Textual built-in

CRUD bindings (Screen/Widget level — views opt in):
  n              new
  e              edit
  d              delete (always via confirm modal)
  enter          open detail
  r              refresh (manual — reactive views usually don't need this)

Navigation bindings (list-like views):
  j, down        down
  k, up          up
  g              top
  G              bottom
  /              search (where supported)

Destructive op convention: NEVER single-key destruction. All delete/cancel/reset
go through modal confirm; modal declares y/n or enter/escape.
"""
from textual.binding import Binding

# --- Global (App level) ---
GLOBAL_BINDINGS = [
    Binding("q", "quit", "退出", show=True),
    Binding("question_mark", "help", "帮助", show=True, key_display="?"),
    Binding("escape", "back", "返回", show=False),
]


# --- CRUD (Widget/Screen level, imported by views) ---
CRUD_BINDINGS_LIST = [
    Binding("n", "new_item", "新建", show=True),
    Binding("e", "edit_item", "编辑", show=True),
    Binding("d", "delete_item", "删除", show=True),
    Binding("enter", "open_item", "打开", show=True),
    Binding("r", "refresh", "刷新", show=False),
]

# --- Navigation (list-like views) ---
NAV_BINDINGS = [
    Binding("j", "cursor_down", "下", show=False),
    Binding("k", "cursor_up", "上", show=False),
    Binding("down", "cursor_down", "下", show=False),
    Binding("up", "cursor_up", "上", show=False),
    Binding("g", "cursor_top", "顶部", show=False),
    Binding("shift+g", "cursor_bottom", "底部", show=False),
    Binding("slash", "search", "搜索", show=False, key_display="/"),
]
