# 评分 (Scoring)

polily 给每个事件打 0-100 分（结构分），然后按阈值划 tier A / B / C：
A = 强候选，B = 备选，C = 跳过。本节配置 tier 边界。

注：每个维度的具体权重（流动性 / 客观性 / 概率空间 / 时间 / 摩擦）
住在 `polily/scan/scoring.py` 的模块常量里 —— 跟评分算法紧耦合，不
暴露给用户编辑。

---

## scoring.thresholds.tier_a_min_score

**默认 70。** 事件总分 ≥ 70 → 标 tier A（强候选）。

**何时调：** 想看到更多事件被打成 A 级（哪怕质量稍差）→ 调到 60。
想极度严格只看顶级事件 → 调到 80+。

---

## scoring.thresholds.tier_b_min_score

**默认 45。** 事件总分在 [45, 70) 区间 → 标 tier B（备选）。低于
45 标 tier C（不出现在主视图，归档）。

**何时调：** 嫌 C 级事件太多 → 调到 50 让边界事件进 C。想捡漏更多
→ 调到 35-40，但 polily 的扫描会被噪声拖慢。

---

## scoring.thresholds.tier_a_require_mispricing

**默认 false。** 是否要求 tier A 事件必须有 mispricing 信号
（crypto vol / multi-outcome max-sum）。

**为什么默认关闭：** 不是所有 polily 用户的 edge 都来自 mispricing；
有些 edge 是结构性（深盘口 + 低摩擦）。开启后 tier A 严格要求"既
有结构 edge 又有定价 edge"，过滤更严但可能错过纯结构机会。

**何时调：** 你的策略主要靠 mispricing → 开启它，过滤更干净。你的
策略允许结构性事件（即便没有定价偏离）→ 关闭（默认）。
