"""v0.11.6 invariant: no raw db.conn.* / self.conn.* outside db.py
EXCEPT inside `with db._lock:` blocks (the §1.5.1 carve-out).

The broad lock migration (v0.11.6 Item 1) replaced ~88 raw call sites
with the canonical `with db.transaction() as conn: conn.<method>(...)`
pattern. The other ~10 sites (trade_engine atomic methods, wallet
commit=False paths, config.py + cli.py BEGIN IMMEDIATE blocks) keep
their explicit transaction code wrapped in `with db._lock:` for thread
safety — see design doc §1.5.1.

This test catches both rules: any `db.conn.<anything>` call outside
db.py must EITHER live inside a `with db._lock:` block OR be a
violation. Regex covers ALL connection methods (execute, executemany,
executescript, commit, rollback, cursor, close), not just execute*,
so future code can't bypass via a different method.
"""
from __future__ import annotations

import re
from pathlib import Path


def _line_inside_locked_block(lines: list[str], lineno_1based: int) -> bool:
    """Return True iff line N is inside an enclosing `with db._lock:` /
    `with self.db._lock:` block (any depth, same function).

    Heuristic: walk backward from target. Track target's indent. If we
    encounter `with (self.)?db._lock:` at strictly LESSER indent, the
    target is inside that block. Stop if we hit a `def `/`class ` at
    lesser indent (that means we left the function).
    """
    target = lines[lineno_1based - 1]
    target_indent = len(target) - len(target.lstrip())
    if not target.strip():
        return False

    lock_pattern = re.compile(r"\bwith\s+(self\.)?db\._lock\s*:")
    boundary_pattern = re.compile(r"^(\s*)(def |class |async def )")

    for i in range(lineno_1based - 2, -1, -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(line) - len(line.lstrip())

        bm = boundary_pattern.match(line)
        if bm and len(bm.group(1)) < target_indent:
            return False

        if line_indent < target_indent and lock_pattern.search(line):
            return True

    return False


def _docstring_line_ranges(text: str) -> set[int]:
    """Return the set of 1-based line numbers that are inside a triple-quoted
    string literal (docstring or otherwise).

    Naïve scanner: walks the source character-by-character, tracking whether
    it's inside a `'''` or `\"\"\"` block. Doesn't try to handle every Python
    edge case (raw/byte prefixes, escaped quotes); good enough to filter
    docstring narrative text from the lock-migration invariant.
    """
    inside_lines: set[int] = set()
    i = 0
    n = len(text)
    line = 1
    in_triple: str | None = None  # one of None, "'''", '\"\"\"'
    in_single: str | None = None  # one of None, "'", '"'
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if in_triple is not None:
            inside_lines.add(line)
            if text.startswith(in_triple, i):
                i += 3
                in_triple = None
                continue
            i += 1
            continue
        if in_single is not None:
            # single-line string — escape handling
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_single:
                in_single = None
            i += 1
            continue
        # not currently inside any string
        if text.startswith(('"""', "'''"), i):
            in_triple = text[i:i+3]
            i += 3
            inside_lines.add(line)
            continue
        if ch in ("'", '"'):
            in_single = ch
            i += 1
            continue
        i += 1
    return inside_lines


def test_no_raw_db_conn_outside_db_py_or_lock():
    """All `db.conn.<method>` outside db.py must be inside `with db._lock:`.

    Catches: execute, executemany, executescript, commit, rollback,
    cursor, close — the entire sqlite3.Connection API surface.
    """
    repo_root = Path(__file__).resolve().parents[1]
    polily_dir = repo_root / "polily"
    db_py = polily_dir / "core" / "db.py"

    pattern = re.compile(r"\b(?:self\.)?db\.conn\.\w+")

    violations: list[tuple[Path, int, str]] = []
    for py_file in polily_dir.rglob("*.py"):
        if py_file.resolve() == db_py.resolve():
            continue
        text = py_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        docstring_lines = _docstring_line_ranges(text)
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if lineno in docstring_lines:
                # Narrative text inside a triple-quoted docstring is
                # documentation, not executable code.
                continue
            if pattern.search(line):
                if _line_inside_locked_block(lines, lineno):
                    continue
                violations.append(
                    (py_file.relative_to(repo_root), lineno, line.strip()),
                )

    if violations:
        msg = (
            f"v0.11.6 invariant violation: {len(violations)} raw "
            f"`db.conn.<method>` call(s) outside polily/core/db.py "
            f"AND outside `with db._lock:` blocks.\n\n"
            f"Two ways to fix:\n"
            f"  (A) Most cases — migrate to `with db.transaction() as "
            f"conn: conn.<method>(...)`.\n"
            f"  (B) Atomicity-critical (BaseException safety, BEGIN "
            f"IMMEDIATE) — wrap with `with db._lock:` and keep explicit "
            f"transaction code. See design doc §1.5.1.\n\n"
            f"Offenders:\n"
        )
        for path, lineno, line in violations[:20]:
            msg += f"  {path}:{lineno}: {line}\n"
        if len(violations) > 20:
            msg += f"  ... and {len(violations) - 20} more.\n"
        raise AssertionError(msg)


def test_no_raw_self_conn_outside_db_py():
    """Same invariant for `self.conn.<method>` — a common spelling
    inside service classes (WalletService, TradeEngine etc.). Allows
    db.py only (where `self.conn` is the legitimate connection ref).
    """
    repo_root = Path(__file__).resolve().parents[1]
    polily_dir = repo_root / "polily"
    db_py = polily_dir / "core" / "db.py"

    pattern = re.compile(r"\bself\.conn\.\w+")

    violations: list[tuple[Path, int, str]] = []
    for py_file in polily_dir.rglob("*.py"):
        if py_file.resolve() == db_py.resolve():
            continue
        text = py_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        docstring_lines = _docstring_line_ranges(text)
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if lineno in docstring_lines:
                continue
            if pattern.search(line):
                if _line_inside_locked_block(lines, lineno):
                    continue
                violations.append(
                    (py_file.relative_to(repo_root), lineno, line.strip()),
                )

    if violations:
        msg = (
            f"v0.11.6 invariant violation: {len(violations)} raw "
            f"`self.conn.<method>` call(s) outside polily/core/db.py "
            f"and outside `with db._lock:` blocks. Migrate to "
            f"db.transaction() or wrap in lock per §1.5.1.\n\nOffenders:\n"
        )
        for path, lineno, line in violations[:20]:
            msg += f"  {path}:{lineno}: {line}\n"
        raise AssertionError(msg)
