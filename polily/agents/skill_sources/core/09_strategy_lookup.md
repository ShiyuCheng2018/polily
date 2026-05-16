<!-- external-only -->
## 9. Polily's Analytical Methodology (runtime lookup)

When the user asks a follow-up question that requires polily's analytical framework — explaining "edge", interpreting `structure_score`, framing position management, deciding what "friction" means for a specific market, walking through how polily would judge a thesis — **do not freelance with generic finance reasoning**. Look up the methodology polily actually uses, in this exact order.

### Why this lookup matters

Polily ships a default analytical methodology (`polily/strategies/default.md` in the polily repo) AND lets users override it with their own version (TUI key `7` → My Strategy → free-form markdown stored at `user_strategy.text` in their `polily.db`). At analysis dispatch time polily's internal agent loads whichever is active. For chat follow-ups via this skill, mirror that decision so your answers stay consistent with what the user has already read in their TUI.

### Step 1 — Resolve `polily.db` path

    DB_PATH=$(python -c 'from polily.core.paths import db_path; print(db_path())')

(Falls back to platform default if polily is installed but not running; see §5 for the full resolution rules.)

### Step 2 — Check which strategy is active

    sqlite3 "$DB_PATH" "SELECT value FROM config WHERE key_path='active_strategy'"

JSON-encoded `"official"` (the default) or `"user"`.

### Step 3a — If active = `"user"`

Read the user's custom methodology directly from their DB:

    sqlite3 "$DB_PATH" "SELECT text FROM user_strategy WHERE id=1"

If `text` is non-empty and coherent, **that IS the methodology**. Use it verbatim as your analytical voice. If it's empty / whitespace / clearly broken, fall through to Step 3b.

### Step 3b — If active = `"official"` OR user_strategy.text unusable

Fetch polily's packaged official methodology from the canonical GitHub source:

    curl -s https://raw.githubusercontent.com/ShiyuCheng2018/polily/master/polily/strategies/default.md

(Human-readable view, useful when citing back to the user:
[github.com/ShiyuCheng2018/polily/blob/master/polily/strategies/default.md](https://github.com/ShiyuCheng2018/polily/blob/master/polily/strategies/default.md))

This is always the **latest master** — polily's methodology evolves with the project, and pulling from master keeps you in sync.

### Step 4 — Apply

Use the loaded methodology as your **analytical voice**:

- Q1-Q5 self-reflective framework (external anchor / catalyst timing / edge vs fair / reverse thesis / vague self-check)
- Event-type dimensions (crypto / political / sports / economic_data / social — each has different focus)
- Position management depth when the user holds a position (thesis_status / action options / stop-loss / cross-event awareness)
- Style & tone rules (conditional framing, friction-transparent, source citation for web data, plain language, no labeling user behavior)

If you produced an answer without consulting the methodology first, your framing risks diverging from what the user just read in their TUI — confusing inconsistency. Always Step 1 → 4 before answering substantive analysis questions.

### When to skip the lookup

For purely state-retrieval questions ("what's my cash balance?", "list my open positions", "when did polily last analyze event X?"), the schema in §3 is sufficient and you can answer directly without loading the methodology. The methodology only matters when the user wants polily's **reasoning framework** applied.
<!-- /external-only -->
