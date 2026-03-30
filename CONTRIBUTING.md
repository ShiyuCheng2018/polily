# Contributing to Polily

Thanks for your interest in contributing! Here's how to get started.

## Setup

```bash
git clone https://github.com/ShiyuCheng2018/polily.git && cd polily
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q  # verify everything works
```

### AI Features (optional)

AI agents require [Claude CLI](https://docs.anthropic.com/en/docs/claude-code):

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

Without Claude CLI, the tool works in rule-based mode (`polily scan --no-ai`).

## Branch Strategy

```
master  ← stable releases, tagged (v0.1.0, v0.2.0)
  ↑
dev     ← integration branch, PRs merge here first
  ↑
feat/*  ← feature branches, cut from dev
fix/*
docs/*
refactor/*
```

### Flow

1. **Cut branch** from `dev`: `git checkout dev && git checkout -b feat/my-feature`
2. **Develop** with TDD (red → green → refactor)
3. **Push** and open PR targeting `dev`
4. **CI passes** + review → squash merge into `dev`
5. **Release**: when `dev` has enough for a version, PR from `dev` → `master`, tag release

### Branch Naming

- `feat/<feature>` — new functionality
- `fix/<issue>` — bug fix
- `docs/<topic>` — documentation
- `refactor/<scope>` — code restructuring

### Versioning (SemVer)

- **patch** (0.1.1): bug fixes only
- **minor** (0.2.0): new features, backward compatible
- **major** (1.0.0): breaking changes

## Development Workflow

1. **Branch** from `dev`
2. **Write tests first** (TDD: red → green → refactor)
3. **Run checks** before pushing:
   ```bash
   pytest tests/ -q
   ruff check scanner/ tests/
   pyright scanner/
   ```
4. **Open a PR** targeting `dev` with a clear description

## Code Style

### Language

- **Code**: English (variable names, comments, docstrings)
- **UI text**: Chinese (terminal output, prompts, notifications) — this will become bilingual in the future
- **Documentation**: English in `docs/`, Chinese in `docs/internal/` (not committed)

### Python

- Python 3.11+, type hints everywhere
- Pydantic for data models and config
- `async` for API/network calls, `sync` for pipeline orchestration
- No unnecessary abstractions — three similar lines beats a premature abstraction
- Config-driven: thresholds, weights, behavior all in YAML

### AI Agents

- All AI goes through `claude -p` CLI, never the `anthropic` SDK
- Every AI agent must have a rule-based fallback
- Agent output parsed from `{"type":"result","result":"..."}` envelope

## Testing

- 339 tests, all must pass before merge
- New features need tests
- Mock AI agents in tests (don't call real Claude CLI)
- Use `make_market()` factory from `tests/conftest.py`

## What to Contribute

- Bug fixes
- New market type classifiers
- Improved scoring heuristics
- Additional AI agent prompts
- i18n / bilingual UI support
- Documentation improvements

## Red Lines

These are non-negotiable project principles:

- Never output definitive trade signals ("buy YES")
- Never auto-execute trades
- Never promise profitability
- Never hide friction costs
- Never break the human-in-the-loop model

## Questions?

Open an issue or start a discussion.
