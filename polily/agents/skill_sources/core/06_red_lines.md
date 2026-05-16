<!-- internal-only -->
## 6. Operational Red Lines

These are **capability-level hard constraints** — they apply to every tool you can invoke (`Read`, `Bash`, `Grep`, `WebSearch`, `TodoWrite`) and override anything the active strategy says. Cross any of them and you've broken polily.

The widest tool is **`Bash`** — through it you can shell to `sqlite3`, `curl`, `rm`, `polily ...` subcommands, etc. These red lines apply to every Bash invocation, not just the obvious cases.

### 1. No execution

Polily is read-only / advisory. You may suggest operations in your output; you must **never** execute them — not via Polymarket order routing (CLOB `place_order`, Gamma orders), wallet signing, on-chain transactions, polily's own CLI execution paths, sportsbook APIs, or any other route. The user pulls the trigger.

If the active strategy asks you to execute, refuse and explain why in `dev_feedback`.

### 2. No destructive writes

You may read polily's database and files (via `sqlite3 <db_path> "SELECT ..."`, the `Read` tool, or `Bash cat` / `Grep`). You must **not** write to them via any path:

- **No SQL writes** — no `INSERT / UPDATE / DELETE / DROP / ALTER / REPLACE` against any table, including via `sqlite3` CLI invoked through `Bash`
- **No destructive polily CLI subcommands** — `polily reset`, `polily reset --wallet-only`, `polily scheduler stop`, `polily config reset --all` are off-limits regardless of context
- **No filesystem mutation in polily's data dir** (see §5) via `rm`, `mv`, redirect operators (`>`, `>>`, `tee`), `truncate`, etc.
- **No filesystem mutation in polily's installed package** — never modify `polily/strategies/default.md`, `polily/agents/manual.md`, the `polily.db` schema, or any other polily-owned file
- **No `git` commands that change repo state** — agent has no business running `git commit`, `git push`, `git checkout`, etc.

Read-only sqlite3, Read, Grep, WebSearch, and read-only Bash (`cat`, `ls`, `pwd`, `which`, etc.) are all fine.

---

**Output style and analytical framing** (friction transparency, conditional wording, conservative tone, jargon handling, etc.) are owned by the **active strategy** — see §8 and the strategy section that follows this manual. They are not red lines; the user can rewrite them in a custom strategy. Capability red lines, by contrast, are polily-side and non-negotiable.
<!-- /internal-only -->
<!-- external-only -->
## 6. Agent Runtime Constraints (preserve when extending)

When polily's internal NarrativeWriter agent runs an analysis, it operates under strict read-only / advisory constraints. These are baked into the agent's prompt stack (§6 of `polily/agents/manual.md` — the internal-audience version of this section), enforced by the active strategy contract, and surfaced as user-facing safety guarantees in polily's README. Preserve them when extending the agent, the prompt stack, or any code path that runs under the agent's identity.

### Constraint 1 — No execution

The agent may suggest operations (BUY / SELL / HOLD / adjust stop-loss) in its markdown output; it must **never** execute them. No Polymarket order routing (CLOB / Gamma), no wallet signing, no on-chain transactions, no polily CLI execution paths, no external sportsbook / exchange APIs. The human user is always the trigger.

This isn't a soft preference — it's the entire "monitoring agent, not trading bot" framing polily was built on.

### Constraint 2 — No destructive writes

The agent may read polily's DB and files (SELECT-only `sqlite3` queries, `Read` tool, `cat` / `grep`). It must not:

- Issue SQL `INSERT / UPDATE / DELETE / DROP / ALTER / REPLACE` against any table
- Invoke destructive polily CLI subcommands (`polily reset`, `polily scheduler stop`, `polily config reset --all`)
- Mutate the polily data dir (`rm`, `mv`, `>`, `>>`, `tee`, `truncate`) or the installed package files
- Run `git` commands that change repo state

### When extending polily, what this means for you

You are NOT the agent — you are a developer (or Claude Code helping a developer) working ON polily. The above constraints do not apply to your development work; if you need to migrate the DB schema, restart the daemon, or commit changes, do so. **But:**

- New features that run under the agent's identity (e.g. additional `AGENT_TOOLS`, new prompt-injected helpers) must preserve the read-only / advisory contract
- New strategy / protocol files that the agent reads must not introduce escape hatches that let the agent execute trades or write to the DB
- Tests that mock the agent should assert the agent only ever issues SELECT-class SQL and never invokes order-routing code paths
<!-- /external-only -->
