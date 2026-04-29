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

---

## movement.weights.crypto.magnitude.price_z_score

**默认 0.15。** crypto 市场该信号偏低 —— 低流动性下假突变多，更倚
重 fair_value_divergence (0.40)。
详见 [信号词汇表 → price_z_score](#price_z_score)。

## movement.weights.crypto.magnitude.book_imbalance

**默认 0.10。** crypto 盘口流动性常稀薄，盘口失衡信号噪声大。
详见 [信号词汇表 → book_imbalance](#book_imbalance)。

## movement.weights.crypto.magnitude.fair_value_divergence

**默认 0.40。** crypto 最重要的 magnitude 信号 —— underlying 价格
变动 + 时间衰减给的 fair value 偏离是 polily 在 crypto 找 mispricing
的核心信号。
详见 [信号词汇表 → fair_value_divergence](#fair_value_divergence)。

## movement.weights.crypto.magnitude.underlying_z_score

**默认 0.20。** underlying (BTC/ETH) 的 z-score 突变是 crypto 市场
反应价格变化的早期指标。
详见 [信号词汇表 → underlying_z_score](#underlying_z_score)。

## movement.weights.crypto.magnitude.cross_divergence

**默认 0.15。** Polymarket binary 跟 perp 市场的偏离；适度信号，避
免被 perp 价格剧烈波动主导分析。
详见 [信号词汇表 → cross_divergence](#cross_divergence)。

## movement.weights.crypto.quality.volume_ratio

**默认 0.40。** 量是否放大是 crypto 异动是否"真实"的最强信号。
详见 [信号词汇表 → volume_ratio](#volume_ratio)。

## movement.weights.crypto.quality.trade_concentration

**默认 0.35。** 是否大单推动；crypto 单笔大单常见但仍需关注。
详见 [信号词汇表 → trade_concentration](#trade_concentration)。

## movement.weights.crypto.quality.volume_price_confirmation

**默认 0.25。** 量价配合度；权重适中以平衡量信号。
详见 [信号词汇表 → volume_price_confirmation](#volume_price_confirmation)。

## movement.weights.political.magnitude.price_z_score

**默认 0.35。** political 市场盘口稳定，z-score 突变更可能反映真实
信息流；权重比 crypto 高。
详见 [信号词汇表 → price_z_score](#price_z_score)。

## movement.weights.political.magnitude.book_imbalance

**默认 0.25。** political 盘口比 crypto 更可信，盘口失衡是有效信号。
详见 [信号词汇表 → book_imbalance](#book_imbalance)。

## movement.weights.political.magnitude.sustained_drift

**默认 0.40。** political 最重要的 magnitude 信号 —— 持续单向漂移
往往对应"真实事件发生"（民调、声明、揭露）。
详见 [信号词汇表 → sustained_drift](#sustained_drift)。

## movement.weights.political.quality.volume_ratio

**默认 0.35。** political 市场异动伴随放量是可信信号。
详见 [信号词汇表 → volume_ratio](#volume_ratio)。

## movement.weights.political.quality.trade_concentration

**默认 0.40。** political 大单常常是"知情人"先动；权重比 crypto 高。
详见 [信号词汇表 → trade_concentration](#trade_concentration)。

## movement.weights.political.quality.volume_price_confirmation

**默认 0.25。** 量价配合度；与 crypto 同权。
详见 [信号词汇表 → volume_price_confirmation](#volume_price_confirmation)。

## movement.weights.economic_data.magnitude.price_z_score

**默认 0.30。** economic_data 市场（如 CPI、就业数据）盘口表现介于
crypto 和 political 之间。
详见 [信号词汇表 → price_z_score](#price_z_score)。

## movement.weights.economic_data.magnitude.book_imbalance

**默认 0.15。** economic_data 盘口流动性常较低，权重适中。
详见 [信号词汇表 → book_imbalance](#book_imbalance)。

## movement.weights.economic_data.magnitude.time_decay_adjusted_move

**默认 0.55。** economic_data 最重要的 magnitude 信号 —— 数据公布
时间是已知的，时间衰减调整后的价格变动直接反映数据预期偏离。
详见 [信号词汇表 → time_decay_adjusted_move](#time_decay_adjusted_move)。

## movement.weights.economic_data.quality.volume_ratio

**默认 0.40。** 数据公布前后量明显放大是 quality 核心信号。
详见 [信号词汇表 → volume_ratio](#volume_ratio)。

## movement.weights.economic_data.quality.trade_concentration

**默认 0.30。** economic_data 单笔集中度低于 political（更多分散
散户参与）。
详见 [信号词汇表 → trade_concentration](#trade_concentration)。

## movement.weights.economic_data.quality.volume_price_confirmation

**默认 0.30。** 量价配合度，跟其他市场类型同权。
详见 [信号词汇表 → volume_price_confirmation](#volume_price_confirmation)。

## movement.weights.default.magnitude.price_z_score

**默认 0.45。** "default" 市场是 polily 不识别市场类型时的兜底；权
重最高的 magnitude 信号是 z-score —— 最通用、最不依赖类型特定数据。
详见 [信号词汇表 → price_z_score](#price_z_score)。

## movement.weights.default.magnitude.book_imbalance

**默认 0.30。** 兜底场景下盘口失衡是次重要 magnitude 信号。
详见 [信号词汇表 → book_imbalance](#book_imbalance)。

## movement.weights.default.magnitude.volume_ratio

**默认 0.25。** 兜底场景下 magnitude 也用 volume_ratio（其他市场
类型把它放在 quality 里）—— 因为 default 不知道有什么 quality 信
号特别重要，所以 magnitude/quality 之间的边界更模糊。
详见 [信号词汇表 → volume_ratio](#volume_ratio)。

## movement.weights.default.quality.volume_ratio

**默认 0.40。** 兜底 quality 也以 volume_ratio 为主，跟 magnitude
里的 volume_ratio 不冲突 —— magnitude 的 volume_ratio 看的是
"是否放量"，quality 的 volume_ratio 看的是"放量是否可信"（不同时
间窗口的均值参考）。
详见 [信号词汇表 → volume_ratio](#volume_ratio)。

## movement.weights.default.quality.trade_concentration

**默认 0.35。** 兜底 quality 中 trade_concentration 与其他市场类型
保持一致权重。
详见 [信号词汇表 → trade_concentration](#trade_concentration)。

## movement.weights.default.quality.volume_price_confirmation

**默认 0.25。** 兜底 quality 中 volume_price_confirmation 与其他市
场类型保持一致权重。
详见 [信号词汇表 → volume_price_confirmation](#volume_price_confirmation)。
