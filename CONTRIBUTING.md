# Contributing to Polily

Thanks for your interest in contributing! Here's how to get started.

## Setup

```bash
git clone https://github.com/ShiyuCheng2018/polily.git && cd polily
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q  # verify everything works (~1721 tests)
```

### AI Features (optional)

AI agents require [Claude CLI](https://docs.anthropic.com/en/docs/claude-code):

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

### Dev/prod data isolation (recommended)

If you also USE polily as a regular user on the same machine (typical for the maintainer + power users), v0.11.0+ defaults data to `~/Library/Application Support/polily/` (production-like). You probably want **repo-local dev data** so:

- Tests + dev sessions don't pollute your real polily data
- Different feature branches can isolate state per worktree
- A dev launchd daemon (`com.polily.scheduler.dev`) coexists with your real prod daemon

#### Option A: direnv (recommended — auto-loads on cd)

```bash
brew install direnv
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc  # or your shell rc
exec zsh
cd polily
cp .envrc.example .envrc
direnv allow
```

Now `cd polily` auto-exports:
- `POLILY_DATA_DIR=$REPO/data` — dev db lives in repo
- `POLILY_LOG_DIR=$POLILY_DATA_DIR/logs` — dev logs live in repo
- `POLILY_LAUNCHD_LABEL=com.polily.scheduler.dev` — dev launchd label distinct from prod

`cd` out of the repo → env auto-unloads → polily uses default platformdirs (prod). Your dev work and real polily data never collide.

#### Option B: shell alias fallback (no direnv)

Add to your shell rc:
```bash
alias polily-dev='POLILY_DATA_DIR=$HOME/MyProjects/polily/data POLILY_LAUNCHD_LABEL=com.polily.scheduler.dev $HOME/MyProjects/polily/.venv/bin/polily'
```

Use `polily-dev` for dev work, plain `polily` for normal use.

#### What this gives you

| Action | dev mode (.envrc loaded) | prod mode (no env) |
|---|---|---|
| `polily` (TUI) | Uses `$REPO/data/polily.db` | Uses `~/Library/Application Support/polily/polily.db` |
| `polily scheduler restart` | Registers `com.polily.scheduler.dev` plist | Registers `com.polily.scheduler` plist |
| `pytest tests/` | Tests use `tmp_path` regardless (the conftest fixture handles isolation) | Same |

**Note**: `.envrc` is gitignored (your local override). `.envrc.example` is the template (in git, copied by every contributor).

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
   ruff check polily/ tests/
   pyright polily/
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
- Agent output parsed from `{"type":"result","result":"..."}` envelope

## Testing

- All tests must pass before merge (currently ~1721 tests + 1 skipped Linux XDG)
- New features need tests
- Mock AI agents in tests (don't call real Claude CLI) — `tests/conftest.py` has helpers
- Use `make_market()` factory from `tests/conftest.py`
- Use `polily_db` fixture for tests that need a real `PolilyDB` (it isolates via `tmp_path` + `POLILY_DATA_DIR` env override)
- If you write a local `service` fixture using `PolilyService()`, **must** include `monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))` — otherwise the test will write to the user's real production db (verified failure mode, see commit `77c8d89`)

## What to Contribute

- Bug fixes
- New market type classifiers
- Improved scoring heuristics
- Additional AI agent prompts
- i18n / bilingual UI support
- Documentation improvements

## Questions?

Open an issue or start a discussion.
