# 异动触发 (Movement)

本节是 polily 判断"某个市场发生了值得 AI 分析的事"的核心。所有参数
影响 daemon 的 Step 3.5 dispatcher 和 movement scorer。

调高阈值 → 更保守，AI 介入更少；调低阈值 → 更激进，AI 调用量增加。

---

## _signals_glossary

定义 weights 子树用到的所有信号语义。每个 weight leaf 通过锚点链接
回到这里，避免 4 个市场类型重复 4 遍同样的描述。

### price_z_score
价格相对最近滑窗的标准差偏离倍数。> 2 标准差视为突变。

### book_imbalance
盘口买卖盘失衡比 (bid_size / ask_size)。> 3 视为单边压力。

### fair_value_divergence
当前价相对 fair value 的偏离百分比（fair value 由 underlying 价格 +
时间衰减计算）。仅 crypto 市场用。

### underlying_z_score
underlying（如 BTC、ETH）的 z-score；仅 crypto 市场用。

### cross_divergence
跨资产偏离信号；仅 crypto 市场用（如 BTC-PERP vs Polymarket BTC 价
格 binary）。

### sustained_drift
价格持续单向漂移强度；仅 political 市场用。

### time_decay_adjusted_move
时间衰减调整后的价格变动；仅 economic_data 市场用。

### volume_ratio
当前 volume 相对最近滑窗均值的倍数。

### trade_concentration
最大单笔成交占比；高值表示"少数大单推动"。

### volume_price_confirmation
成交量与价格变动的相关性。

---

## movement.magnitude_threshold

**默认 70。** 异动算出的"幅度分数"（0-100）超过这个阈值才会被视为
"可能重要"。幅度分数综合了价格 z-score、盘口失衡、fair-value 偏离
等信号（按市场类型加权，见 weights 子树）。

**默认 70 的来历：** v0.7 阶段观察到低于 70 的异动里 80%+ 是噪声。
权衡"AI 被噪声触发太多 vs 错过真信号"的经验值。

**如何调：** 想让 AI 更频繁介入可降到 50-60；想极度保守可升到 80+。
调低会显著增加 daemon 的 AI 调用量，留意成本。

---

## movement.quality_threshold

**默认 60。** 与 magnitude_threshold 串联使用 —— AI 触发要求
**两个分数都过线**。质量分数衡量"信号有多干净"（成交量配合度、单笔
集中度、量价确认度）。

**为什么有两层门槛：** 大幅价格波动（magnitude 高）但成交稀薄
（quality 低）可能是单笔大单噪声，不值得 AI 分析。

**如何调：** 调低 quality 让 polily 更愿意分析"剧烈但孤立"的波动；
调高让 polily 只在"剧烈且广泛"的波动出现时介入。

---

## movement.daily_analysis_limit

**默认 10。** 每个市场每天最多触发的 AI 分析次数。防止单个市场反复
触发 magnitude/quality 阈值 → AI 调用爆炸。

**何时调：** 如果某些高活跃市场每天用满 10 次但你想看到每次分析，
可调高到 20-30。降到 1-3 适合极度成本敏感的场景。

---

## movement.min_history_entries

**默认 5。** 一个市场需要至少这么多 movement_log 行才开始 score。
低于此数 score 计算被跳过（数据不足，z-score 不可信）。

**何时调：** 几乎不需要调。如果你觉得 polily 上线新事件后"分析启动
太慢"可降到 3，但低于 3 时 z-score 会很噪。

---

## movement.stale_threshold_seconds

**默认 600 秒 (10 分钟)。** 比这个老的 movement_log 数据被视为 stale
跳过 score。防止 daemon 用早就过期的数据触发分析。

**何时调：** 如果你的网络/poll 长时间断开后想让 polily 仍信任更老
数据，调高到 1800 (30 分钟) 或 3600 (1 小时)。低于 60 秒在 30 秒
poll 间隔下会让大量 score 计算被跳过。
