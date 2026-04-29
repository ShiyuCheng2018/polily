# 钱包 (Wallet)

polily 的虚拟钱包用于 paper trading（模拟交易）—— 验证策略而不真
正下单。本节配置初始资金。

---

## wallet.starting_balance

**默认 100.0 USD。** 钱包重置时的初始现金量；也是首次安装 polily
时分配的起始资金。

**何时调：** 你的小账户实际只有 50 美金 → 改成 50.0，让 paper 交
易的 sizing 更贴近真实。你想在 paper trading 中练习更大账户的纪律
→ 升到 500 或 1000。

注意：调大 starting_balance 不影响实际资金；polily 是 paper trading，
钱包数字仅用于内部 P&L 统计 + 风控建议。

**重置：** 通过 ⚙ 配置 改完之后，运行 `polily reset --wallet-only`
让新值生效（直接清空钱包并按新 balance 初始化）。
