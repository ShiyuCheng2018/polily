# Runtime i18n Design

> Status: Draft · Branch: `feat/runtime-i18n` · Target: TUI 多语言支持 + 运行时切换

## 1. 目标

1. **新增英文支持**，第一阶段 zh / en 双语并行。
2. **可拓展**：未来加日语、韩语等，只需新增一个语言文件，不改业务代码。
3. **运行时切换**：用户在 TUI 内通过快捷键切换语言，所有可见界面立即生效，**无需重启**。
4. **持久化**：用户选择的语言下次启动自动恢复。

## 2. 涉及范围

| 模块 | 改动 |
|---|---|
| `polily/tui/` | 主要改动：所有视图/组件/绑定的中文字面量替换为 `t(key)` 调用 |
| `polily/tui/i18n/` | 新增包：catalog 加载 + `t()` API + 切换接口 |
| `polily/core/config.py` | `TuiConfig` 加 `language` 字段（启动默认值） |
| `polily/core/events.py` | 新增 `TOPIC_LANGUAGE_CHANGED` 常量 |
| `polily/core/user_prefs.py` | **新文件**：DB 持久化用户偏好（K/V） |
| `polily/core/db.py` | schema 加 `user_prefs` 表 |
| **不改动** | `core/` 业务逻辑、`scan/`、`monitor/`、`daemon/`、`agents/`、CHANGELOG.md、agent prompts |

## 3. 总体架构

```
                        ┌────────────────────────────────────┐
                        │  catalogs/zh.json                  │
                        │  catalogs/en.json                  │
                        │  catalogs/ja.json   (后续添加)     │
                        └─────────────┬──────────────────────┘
                                      │ 启动时全部加载到内存
                                      ▼
        ┌──────────────────────────────────────────────────────┐
        │  polily/tui/i18n/__init__.py  (进程内单例)           │
        │   ─ _catalogs: dict[lang, dict[key, str]]            │
        │   ─ _current_lang: str   (受 RLock 保护)             │
        │                                                      │
        │   API:                                               │
        │     init_i18n(catalogs, default)  ← 启动             │
        │     t(key, **vars) -> str         ← 视图查询         │
        │     set_language(lang)            ← 用户切换         │
        │     current_language() -> str                        │
        │     available_languages() -> list[str]               │
        └──────────────┬───────────────────────────────────────┘
                       │
        ┌──────────────┴────────────────┐
        │  视图查询 t("wallet.balance") │  ← 每次 render 都现读
        └───────────────────────────────┘
                       ▲
                       │ refresh(recompose=True)
                       │
        ┌──────────────┴────────────────┐
        │  view._render_all (existing)  │
        └──────────────▲────────────────┘
                       │ once_per_tick + dispatch_to_ui
                       │
        ┌──────────────┴────────────────────────────┐
        │  EventBus.publish(TOPIC_LANGUAGE_CHANGED) │
        └──────────────▲────────────────────────────┘
                       │
        ┌──────────────┴───────────────────┐
        │  PolilyApp.action_toggle_language│
        │   ├─ set_language(next)          │
        │   ├─ service.save_lang_pref()    │  → DB user_prefs 表
        │   ├─ publish 事件                │
        │   └─ refresh_bindings_after_*    │  → 见 §6
        └──────────────────────────────────┘
```

## 4. 模块设计

### 4.1 `polily/tui/i18n/`

```
polily/tui/i18n/
  __init__.py        # API: t / set_language / current_language / init_i18n
  loader.py          # 启动时扫 catalogs/*.json
  catalogs/
    zh.json
    en.json
```

**API 契约**（`__init__.py`）：

```python
def init_i18n(catalogs: dict[str, dict[str, str]], default: str) -> None: ...
def t(key: str, **vars) -> str: ...
def set_language(lang: str) -> None: ...
def current_language() -> str: ...
def available_languages() -> list[str]: ...
```

**关键决策**：

- `t()` **每次调用现读 `_current_lang`**。不缓存、不用 thread-local。切换语言后下一次 render 自然就是新值。
- 用 `RLock` 保护 `_current_lang` 和 `_catalogs`。开销可忽略（TUI render 频率 ≤ 几十次/秒）。
- catalog 启动一次性全量加载到内存。语言文件 < 100 KB，没必要懒加载。
- **缺失 key 行为**：fallback 到 zh，再 fallback 到 key 本身，并记 warning log。**绝不抛异常**——渐进迁移期间不能让 UI 崩。
- `t(key, **vars)` 内部用 `str.format(**vars)`。模板写法：`"正在分析... ({elapsed}s)"`。

### 4.2 Catalog 文件格式（JSON）

按 `视图.元素` 命名：

```json
{
  "binding.quit": "退出",
  "binding.help": "帮助",
  "binding.back": "返回",
  "binding.toggle_language": "切换语言",
  "wallet.balance": "当前余额",
  "wallet.transactions": "交易流水",
  "wallet.txn_type.topup": "充值",
  "wallet.txn_type.withdraw": "提现",
  "scan.analyzing": "正在分析... ({elapsed}s)",
  "monitor.col.event": "事件",
  "monitor.col.score": "结构分"
}
```

**为什么用 JSON 而不是 gettext .po**：项目无 i18n 历史负担；JSON 简单、IDE 友好、CI 易校验缺失 key。
**为什么 key 用点分层级而不是英文原文**：中英都是一等语言，没有"原文"的概念；层级 key 便于按视图组织。

**新增语言** = 丢一个 `<lang>.json` 文件。`loader.py` 启动时扫目录，文件名即 lang code，无需中央注册表。

### 4.3 切换通知（复用 EventBus）

`polily/core/events.py` 新增：

```python
TOPIC_LANGUAGE_CHANGED = "lang.changed"   # payload: {"language": str}
```

放 `core/` 而不是 `tui/`，是因为 EventBus 本身在 core，topic 常量集中管理符合现有惯例。

### 4.4 视图接入模式（统一）

每个视图新增两段代码（其它都用现成的）：

```python
def on_mount(self):
    # ... existing subscriptions
    self.service.event_bus.subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

def on_unmount(self):
    self.service.event_bus.unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

def _on_lang_changed(self, payload):
    dispatch_to_ui(self.app, self._render_all)   # 已有方法

# _render_all 已经存在，被 @once_per_tick 装饰
```

**为什么不用 watcher 或 reactive 属性**：项目已经统一用 EventBus + `@once_per_tick` 模式（见 `polily/tui/_dispatch.py`）。新机制只会增加心智负担。

### 4.5 切换动作（PolilyApp）

```python
# polily/tui/app.py
async def action_toggle_language(self) -> None:
    langs = available_languages()
    next_lang = langs[(langs.index(current_language()) + 1) % len(langs)]
    set_language(next_lang)
    self.service.save_language_preference(next_lang)
    get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": next_lang})
    self._refresh_bindings_after_language_change()   # ← 见 §6
```

绑定到 `polily/tui/bindings.py::GLOBAL_BINDINGS`：

```python
Binding("alt+l", "toggle_language", t("binding.toggle_language"), show=False)
```

**UX 选择：循环切换 vs Modal 选择器**

- 当前阶段（zh/en 两种）→ 单键循环切换最快
- 未来 ≥ 4 种 → 加一个 modal 选择器，快捷键作为 power-user 通道保留

### 4.6 持久化

**不回写 YAML 配置文件**。`config.yaml` 是用户编辑的"启动默认值"，应用不应该自动改写它（容易和 git 冲突，破坏用户的注释）。

**采用 DB K/V 表**，与项目"data/polily.db 是单一数据源"的原则一致：

```sql
CREATE TABLE IF NOT EXISTS user_prefs (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

封装在 `polily/core/user_prefs.py`（~30 行）。`PolilyService` 持有访问方法。

**启动时语言确定优先级**：

```
DB user_prefs.language  >  config.tui.language  >  "zh"
```

`config.tui.language` 仍然存在，作为新装机用户/未做选择时的默认值，方便 ops 通过 YAML 预置。

## 5. 数据/字符串迁移策略

### 5.1 现状盘点

- ~150+ 处硬编码中文，分布在 16 个 view 文件 + bindings + modals
- 字符串模式：
  - inline 字面量（~70%）：`Label("当前余额")`、`Binding("q", "quit", "退出")`
  - 模块级 dict（~15%）：`_TX_TYPE_LABEL = {"TOPUP": "充值", ...}`
  - f-string 模板（~10%）：`f"正在{verb}... ({live:.0f}s)"`
  - 枚举查表（~5%）：`i18n.translate_status()` —— 现有 stub，需要一并改造
- 后端少量 chinese：`polily/agents/narrative_writer.py:73-76` 错误恢复提示。**第一阶段不动**——这是给 LLM 看的提示词，不是给用户看的 UI 文案。

### 5.2 现有 `polily/tui/i18n.py` 的处理

现有的 stub 模块（38 行，只有 `STATUS_LABELS` / `TRIGGER_LABELS`）需要：
1. 内容**搬到 catalog**（key: `status.pending`、`trigger.manual` 等）
2. 模块从单文件改为 package（`polily/tui/i18n/`）
3. `translate_status()` / `translate_trigger()` 改成 `t(f"status.{x}")` 的薄封装，保留向后兼容直到调用点全部迁移完。

### 5.3 迁移顺序

| 阶段 | 范围 | 验收 |
|---|---|---|
| Spike | 基础设施 + `wallet.py` 视图 + 切换快捷键 | 运行时切换 wallet 视图 + footer 文案能跟着变 |
| 批量 | 每 PR 转 2-3 个视图 | `zh.json` / `en.json` key 集合一致（CI 检查） |
| 收尾 | 残留中文字面量扫零 | grep 全部源码无中文 unicode（除 catalog） |

## 6. 棘手问题：Textual `BINDINGS` 的 footer 刷新

> 用户硬约束：**(1) footer 文案必须跟随语言切换**；**(2) 不能丢失当前 UI 状态**（菜单选中、滚动位置、打开的 modal、所在子页面）。

> 这是本设计**唯一需要 spike 验证**的环节。下面的根因分析基于 textual 8.2.4 源码（`.venv/lib/python3.12/site-packages/textual/`）。

### 6.1 根因：Textual 内部三段冻结

切换语言时 footer 不变，**不是单一原因**，是三段独立的"冻结"叠加：

#### 冻结点 ① ：`Binding` 是 frozen dataclass

`textual/binding.py:54-85`：

```python
@dataclass(frozen=True)
class Binding:
    key: str
    action: str
    description: str = ""
    ...
```

`binding.description` **不能赋值**，赋值会抛 `FrozenInstanceError`。要"改文案"必须**新建一个 Binding 实例**。

#### 冻结点 ② ：`BINDINGS` 在模块导入时就字面量化了

源码里写：

```python
GLOBAL_BINDINGS = [Binding("q", "quit", "退出", show=True), ...]
```

Python 解释器一执行这行，`"退出"` 就成了字符串字面量、被塞进 `Binding` 实例。后续无论 `t()` 怎么变，这个 list 不会自动重算。要"重新求值"必须**把 BINDINGS 写成函数**（每次调用现求值）。

#### 冻结点 ③ ：`_bindings` 在类定义 + 实例化时双重快照

`textual/dom.py:591` (类定义时)：

```python
cls._merged_bindings = cls._merge_bindings()   # 走 MRO 把 BINDINGS 合并成 BindingsMap
```

`textual/dom.py:218-222` (实例化时)：

```python
self._bindings = (
    BindingsMap()
    if self._merged_bindings is None
    else self._merged_bindings.copy()
)
```

每个 DOMNode 的 `_bindings` 是从类级 `_merged_bindings` 拷出来的。**就算我们改了源码里的 `BINDINGS` 列表，已经存在的实例的 `_bindings` 也不会变**。要更新得**手动赋值新的 `BindingsMap` 给 `node._bindings`**。

### 6.2 修正一个先前误判：`refresh_bindings()` **真的会让 Footer 重 compose**

我之前怀疑 `refresh_bindings()` 不一定刷新 description —— **错了，它真会重 compose**。链路如下：

`textual/screen.py:393-395`：

```python
def refresh_bindings(self) -> None:
    self.bindings_updated_signal.publish(self)
```

`textual/widgets/_footer.py:330-335` + `:351-352`：

```python
def on_mount(self) -> None:
    self.screen.bindings_updated_signal.subscribe(self, self.bindings_changed)

def bindings_changed(self, screen):
    self._bindings_ready = True
    if not screen.app.app_focus:
        return
    if self.is_attached and screen is self.screen:
        self.call_after_refresh(self.recompose)
```

`Footer.compose()`（`_footer.py:266-328`）会**重新读 `screen.active_bindings`**，重新 yield 每个 `FooterKey(..., binding.description, ...)`。

**所以 footer recompose 这一段是免费的，问题全部在"recompose 时读到的 Binding 还是旧实例"。**

### 6.3 完整链路图

```
切换语言:
  ┌──────────────────────────────────────┐
  │ 1. set_language("en")  → catalog 切换│  ← i18n 模块就绪
  └──────────────────────────────────────┘
                 │
                 │ 但下面这些都还指向旧 description:
                 ▼
  ┌──────────────────────────────────────┐
  │ app._bindings  → BindingsMap         │  ← 含旧 Binding 实例
  │ screen._bindings → BindingsMap       │  ← 同上
  │ widget._bindings → BindingsMap (×N)  │  ← 焦点链/子树上每个有 BINDINGS 的 widget
  │ modal._bindings (如果 modal 开着)    │  ← 同上
  └──────────────────────────────────────┘
                 │
                 │ 必须手动逐个替换为新 BindingsMap (用 _make_bindings() 现求 t())
                 ▼
  ┌──────────────────────────────────────┐
  │ 2. screen.refresh_bindings()         │
  │     → 触发 bindings_updated_signal   │
  │     → Footer.bindings_changed()      │
  │     → Footer.recompose()             │
  │     → 重读 screen.active_bindings    │
  │     → 这次拿到的是新 Binding 实例 ✓ │
  └──────────────────────────────────────┘
```

### 6.4 候选方案矩阵（修正版）

| # | 名称 | 状态 | 做法 | 主要风险 |
|---|---|---|---|---|
| 1 | rebuild + refresh_bindings | 🟡 spike 通过但**未选用** | 把 BINDINGS 改成 `_make_bindings()` 方法；切语言时遍历 app + screen + 焦点链 + 开着的 modal，逐个替换 `_bindings`；调 `screen.refresh_bindings()`；同时手动 `query + update` 每个视图/modal 内的 Static/Label | 依赖私有 `_bindings` 属性；**两条独立刷新链**（`_bindings` 一条、Static/Label 文本另一条）任何一条漏一处都会出残留；spike 中 modal 漏处理 Static 直接崩；20+ 个类需要改造 |
| 2 | re-push screen | ❌ 否决 | `pop_screen + push_screen` | 用户硬约束：状态不能丢 |
| 3 | 不改 footer | ❌ 否决 | footer 永远英文 | 用户硬约束：footer 必须跟随 |
| 4 | **自定义 I18nFooter (subclass)** | ✅ **选用** | 继承 Textual `Footer`，只 override `compose()` 把 `binding.description` 替换为 `t(f"binding.{action}")`；订阅 `TOPIC_LANGUAGE_CHANGED` 触发 `self.recompose()`；BINDINGS 保持普通常量；视图内文本用 `t(...)` + 现有 `_render_all` 模式自然刷新 | 跟 Textual `Footer.compose()` 实现细节耦合（升级时可能需要同步改 compose 内部逻辑） |
| 5 | Keymap API | ❌ 否决 | 想用 textual 公开的 keymap 机制重映射 description | 已查源码 `textual/binding.py:38`：`Keymap = Mapping[BindingIDString, KeyString]` —— **只能改键位不能改 description**，不适用 |
| C | property 注入 | ❌ 否决 | Binding 子类用 property 动态返回 description | Binding 是 frozen dataclass，property 不可行 |

### 6.5 Spike 计划

**目标**：在 `scripts/spike_i18n_footer.py` 写一个最小 Textual app，分别验证方案 1 和方案 4，根据实际表现选定主方案。

> 方案 5 (Keymap) 已被源码证伪，不进入 spike。

**spike app 设计**：
- 一个 `App`，BINDINGS 包含 `q quit / l toggle_lang`
- 一个 `Screen`，BINDINGS 包含 `r refresh / d delete`
- 屏幕里放一个 `Input`（焦点 widget，用来验证焦点链上的 widget 也要 rebuild）
- 一个 `ModalScreen`，按 `m` 打开（验证 modal 场景）
- 切语言后，footer 上每条 binding 的 description 都应该跟着切

**验证矩阵**（每种方案分别跑）：

| 场景 | 期望 footer description 跟随 |
|---|---|
| 没焦点，无 modal | ✓ |
| 焦点在 Input 上 | ✓ |
| modal 打开时 | ✓ |
| 切回中文再切回英文 | ✓（无累积污染） |

**附带要观察的**：
- 是否依赖私有属性（`_bindings`、`_merged_bindings`）
- 切换有无可见闪烁
- 是否需要 `call_after_refresh` 之类的延迟调度
- textual 升级风险评估

### 6.6 Spike 结果

**测试日期**: 2026-04-26 · **Textual 版本**: 8.2.4 · **测试人**: 用户手动交互验证

**测试矩阵结果**：

| 场景 | 方案 1 (rebuild) | 方案 4 (custom Footer) |
|---|---|---|
| 启动看到中文 footer | ✅ | ✅ |
| 按 F2 footer 切英文 | ✅ | ✅ |
| 焦点在 Input 上时切语言 (Input 自己的 ctrl+s 也跟随) | ✅ | ✅ |
| modal 打开时切语言 | 🐞 spike 代码漏处理 modal 内 Static 导致 `AttributeError` 崩溃；架构本身可行，加 id + update 后通过 | ✅ 一次通过 |
| 反复切换 (累积污染检查) | ✅ | ✅ |
| 切换瞬间闪烁 | 无 | 无 |
| 退出 (F10) | ✅ | ✅ |

**两条独立刷新链 vs 单一刷新链**（这是最关键的发现，直接决定方案选择）：

| 工作项 | 方案 1 | 方案 4 |
|---|---|---|
| 每个有 BINDINGS 的类 | 必须 `_RebuildableMixin` 子类化 + 写 `_bindings_factory()` | 不动，BINDINGS 仍然是常量 |
| 每个含 Static/Label 的视图 | 必须给每个文本 widget 加 id + 在 `action_toggle_lang` 里手动 `query + update` | 文本字面量直接写 `t(...)`，靠现有 `_render_all` + `recompose=True` 自然刷新 |
| walk DOM 树 | 必须遍历 `screen_stack` + 每个 screen 子树 | 不需要 |
| modal / 焦点链 | 必须显式处理（容易漏 — spike 第一次就漏） | 不需要 |
| Footer 文案 | `_bindings` 替换 + `refresh_bindings()` | `I18nFooter.compose` 时现读 `t(f"binding.{action}")` |
| Polily 实际 footprint | 16 个 view + 多个 modal + bindings.py + 每个有 BINDINGS 的 widget = **20+ 个类要改造** | 一个 `I18nFooter` (~30 行) + 替换 `Footer()` 调用 + 视图沿用现有 `_render_all` 模式 |

**核心结论**：

方案 1 把"重新求值文案"拆成两条独立链路 —— footer 走 `_bindings` rebuild，view 内文本走手动 update。**两条链都不能漏一处**，spike 第一次跑就在 modal 漏了一处直接崩。

方案 4 只有一条链路：**所有可见文案都在 compose 时现读 `t()`**。视图用项目已有的 `EventBus + once_per_tick + recompose=True` 重新 compose，footer 用自定义 widget 同样在 compose 时现读 —— **统一的心智模型**。

**对耦合点的判断**：
- 方案 1 跟 Textual 的耦合点是 `_bindings` 私有属性（数据耦合）
- 方案 4 (subclass Footer) 的耦合点是 `Footer.compose()` 实现细节（行为耦合）

行为耦合在升级时通常会以可见的报错或显示异常表现出来，数据耦合更容易静默失效。**方案 4 升级风险更可控**。

**最终选定**：方案 4 (I18nFooter subclass)。

### 6.7 方案 4 细化设计

```python
# polily/tui/widgets/i18n_footer.py
from textual.widgets import Footer

class I18nFooter(Footer):
    """继承内置 Footer，只在 compose 时把 binding.description 替换为 t(f'binding.{action}')。
    
    其余特性 (compact 模式、command palette dock、key groups、mouse 点击模拟键、styles)
    全部沿用父类 Footer，不重写。
    """

    def on_mount(self):
        super().on_mount()
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self):
        super().on_unmount()
        get_event_bus().unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload):
        dispatch_to_ui(self.app, self.recompose)

    def compose(self):
        # 大体抄父类 Footer.compose() (textual/widgets/_footer.py:266-328)
        # 唯一改动: 每处用到 `binding.description` 的地方, 改成
        #   t(f"binding.{binding.action}") or binding.description
        # (catalog 缺 key 时 fallback 到 binding 自带的 description)
        ...
```

**约束**：BINDINGS 写法**不需要改**，但 description 字段必须保持**非空**（否则 `Binding.make_bindings` 会强制 `show=False`）。建议用占位字符 `" "` 或者写成英文短描述当 fallback。

**catalog 命名约定**：`binding.<action_name>` —— action 名直接当 catalog key 后缀。


## 7. 测试策略

| 测试类型 | 内容 |
|---|---|
| 单元 | `t()` 缺失 key 的 fallback 行为 / `set_language` 切换后 `t()` 立即生效 |
| 单元 | catalog loader 扫描目录、容错（坏 JSON、空文件） |
| 单元 | `user_prefs` K/V CRUD |
| 单元 | catalog key 集合一致性（zh.json / en.json key 完全相同） |
| 集成 | 切换语言后 EventBus 发布事件、订阅视图收到回调 |
| 手动 | spike 验证 footer 是否随语言切换刷新 |
| CI | grep 检查源码无残留中文字面量（catalog 目录除外） |

## 8. 落地分阶段

| PR | 内容 | 关注点 |
|---|---|---|
| PR-1 (Spike) | i18n 包基础设施 + `user_prefs` 表 + `wallet.py` 视图迁移 + 切换快捷键 | 验证 §6 的 footer 刷新是否真的有效 |
| PR-2..N | 每 PR 迁移 2-3 个视图，扩充 catalog | 保持 zh/en key 集合一致 |
| PR-final | bindings.py + 残留扫零 + CI gate | grep 残留中文 |

## 9. 决策小结

| 决策点 | 选择 | 备选 | 理由 |
|---|---|---|---|
| 语言状态位置 | `tui/i18n` 进程内单例 | PolilyConfig 字段 | Pydantic 不可变；UI 状态不污染 core |
| catalog 格式 | JSON | YAML / .po (gettext) | 简单、IDE 友好、CI 易校验 |
| catalog 加载时机 | 启动一次性全量 | 懒加载 | 文件小，省去并发复杂度 |
| 切换 UX | 快捷键循环 | Modal 选择器 | 当前 2 种语言够用；未来再加 modal |
| 持久化位置 | DB `user_prefs` 表 | 回写 YAML | 不污染用户配置文件 |
| 通知机制 | 复用 EventBus + `TOPIC_LANGUAGE_CHANGED` | watcher / reactive | 项目既有模式 |
| Binding 刷新 | `I18nFooter` (subclass `Footer` + 订阅 `TOPIC_LANGUAGE_CHANGED`) | rebuild `_bindings` + `refresh_bindings()` | spike 后选定: 单一刷新链路, 视图用 `_render_all` 自然刷新, footer 由 I18nFooter 接管, 心智模型统一 (详见 §6.6) |
| 缺失 key | fallback + log | 抛错 | 渐进迁移期不能崩 |
| key 命名 | `view.element` 点分层级 | 英文原文 | 中英都是一等语言 |
| 后端中文 | 第一阶段不动 | 一起翻 | 缩小爆炸半径；agent prompts 是给 LLM 不是给用户 |
| changelog | 不翻译 | 双份 markdown | 维护成本太高，开源惯例 |

## 10. 非目标（明确不做）

- 不翻译 CHANGELOG.md
- 不翻译 agent prompts（`polily/agents/prompts/*.md`）
- 不翻译日志、错误堆栈、内部 debug 输出
- 不做 RTL 语言支持
- 不做时区/数字/货币本地化（这些是 i10n / l10n 的更大话题，本次只做 i18n）
- 不在第一阶段做 modal 语言选择器
