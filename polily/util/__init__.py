"""Cross-cutting utilities not tied to any specific subsystem.

Sub-modules in this package should be:
- Pure (no side effects beyond the obvious — e.g., a `read_*` helper may
  read a file, but it shouldn't mutate global state).
- Dependency-light (avoid pulling in heavy modules unless required).
- Easy to test in isolation (no implicit DB / scheduler / TUI assumptions).
"""
