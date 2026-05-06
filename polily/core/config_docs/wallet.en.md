# Wallet

Polily's virtual wallet powers paper trading — validate strategies
without putting real money in. This section configures the seed cash.

---

## wallet.starting_balance

**Default 1000.0 USD.** Initial cash on wallet reset; also the seed
amount when polily is installed for the first time.

**When to change it:** Your real Polymarket account size is $X → set to
X.0 so paper trading mirrors your live constraints. The value only
shapes position-size simulation; it does not affect structure scoring.

Note: increasing `starting_balance` does NOT touch real money; polily is
paper trading only — the wallet number drives internal P&L accounting +
risk-sizing suggestions.

**To apply a change:** after editing in ⚙ Config, run
`polily reset --wallet-only` so the new balance takes effect (the command
clears the wallet and re-seeds it at the new balance).
