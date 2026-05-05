# 错误定价 (Mispricing)

polily 找两类 mispricing：(1) crypto 市场用隐含波动率检测概率扭曲，
(2) multi-outcome 市场看互斥 outcome 的概率和是否远离 1.0。本节配
置触发阈值。

---

## mispricing.enabled

**默认 true。** mispricing 检测的总开关。关闭后 polily 跳过整个
mispricing 模块（评分仍正常进行，但 mispricing card 不会显示）。

**何时调：** 你想做"纯结构"分析（不关心定价偏离）→ 关闭。99% 的
用户不该改这个。

---

## mispricing.crypto.volatility_lookback_days

**默认 30 天。** 计算 crypto underlying 实现波动率的滑窗长度。

**何时调：** 你认为最近一个月波动率不能代表"normal regime"（如重
大事件后）→ 缩短到 7-14 天，让算法对近期变动更敏感。但样本太小会
产生噪声估计。

---

## mispricing.crypto.min_deviation_pct

**默认 0.08 (8%)。** Polymarket binary 价格相对 vol-implied 价格
偏离超过这个百分比才标记 mispricing。

**何时调：** 想看更多潜在 mispricing → 降到 0.05。想只看显著偏离
→ 升到 0.15。注意 8% 在 crypto 高 vol 期可能是"正常 noise"，低
vol 期可能是"显著信号"。

---

## mispricing.multi_outcome.enabled

**默认 true。** multi-outcome 检测的子开关（前提 mispricing.enabled
也开启）。

**何时调：** 你只关心 crypto mispricing → 关掉这个。

---

## mispricing.multi_outcome.max_sum_deviation

**默认 0.10。** 多 outcome 市场（如选举多候选人）所有 outcome 的
yes_price 之和应该接近 1.0；偏离超过这个值（即 sum < 0.9 或
sum > 1.1）触发 mispricing 标记。

**何时调：** 想捕捉小幅 sum 偏离 → 降到 0.05。想只看显著偏离 →
升到 0.20。注意 sum 偏离 = 套利机会但执行有摩擦（fee + slippage），
0.10 通常已经是"扣 fee 后还赚"的下限。
