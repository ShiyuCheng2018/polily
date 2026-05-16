# 当前策略 (Active Strategy)

选择 polily NarrativeWriter agent 在生成分析时使用哪份策略。策略不
是普通参数 —— 它是 agent 在原始价格 + 结构数据之上叠加的高层分析
姿态（非对称止损偏好、vol arb 取向、自定义输出段落等）。

---

## active_strategy

**默认 `"official"`。** 每次 NarrativeWriter 调度前加载的策略文本。

**取值：**
- `"official"` — 使用 polily 内置的默认策略
  (`polily/strategies/default.md`)
- `"user"` — 使用 `user_strategy` 表里的 markdown 文本，通过 TUI
  策略页（按键 `7`）编辑

**热切换：** 切换此设置在下一次分析调度时生效；正在跑的分析仍按
切换前的策略完成。

**何时切到 `"user"`：** 当你有明确的分析倾向想让 agent 持续遵循 ——
比如更看重信息差而不是 vol arb、非对称仓位规则、或者官方策略不会
产出的自定义输出段落。

**提示：** 在你形成清晰偏好之前，保持 `"official"`。内置策略是 polily
基准对照的版本。
