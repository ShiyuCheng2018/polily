"""v0.11.0 first-launch data migration: legacy ./data/polily.db → paths.db_path().

Triggered ONLY from interactive contexts (TUI bootstrap). The daemon
launchd context never calls this — daemons must inherit a populated
data dir from the user's first interactive run, or the user runs the
TUI once before starting the daemon.

Marker file (in legacy dir) suppresses re-prompt: once the user has
answered yes-or-no, we never ask again on subsequent launches.

Whis-review S9: when ``--data-dir`` CLI flag is explicitly set, the CLI
callback short-circuits BEFORE calling ``prompt_and_migrate``. The user
has already declared intent for a specific data location; asking them
about legacy ``./data/polily.db`` would be confusing. The skip lives at
the callback orchestration layer (``polily/cli.py:main``), NOT in this
module — this module remains pure and always prompts when conditions
match.
"""
from __future__ import annotations

import contextlib
import logging
import shutil
import sys
from pathlib import Path

from polily.core import paths

logger = logging.getLogger(__name__)

MARKER_FILENAME = ".migrated_to_v0.11.0"


def needs_migration() -> bool:
    """True iff legacy ./data/polily.db exists, new path is empty, and
    no marker has been placed in the legacy dir.

    Pure inspection — no side effects, no I/O beyond stat.
    """
    legacy_db = paths.legacy_db_path()
    if not legacy_db.exists():
        return False  # no legacy install
    new_db = paths.db_path()
    if new_db.exists():
        # New path already populated; user has migrated or run fresh.
        return False
    marker = paths.legacy_data_dir() / MARKER_FILENAME
    # marker present → user has already answered (yes or no); suppress re-prompt
    return not marker.exists()


def perform_migration() -> None:
    """Copy legacy db (and WAL files) to the new resolved path. Creates the
    marker in the legacy dir on success.

    Raises OSError on filesystem failures; caller (`prompt_and_migrate`)
    catches and prints to stderr.

    v0.11.0 fix (Whis-review v2 post-mortem): on OSError mid-copy, cleanup
    partially-copied files at the new path before re-raising. Without this,
    a partial copy leaves new_dir with a mismatched db + wal/shm trio, and
    next launch's needs_migration() returns False (because new db exists),
    locking the user out of retry. With cleanup, the new path is empty
    again so needs_migration() correctly returns True on retry.
    """
    legacy_dir = paths.legacy_data_dir()
    legacy_db = paths.legacy_db_path()
    if not legacy_db.exists():
        return  # nothing to do

    new_dir = paths.data_dir()  # creates dir if missing

    # Copy main db file + WAL/SHM if present.
    copied_files: list[Path] = []
    try:
        for suffix in ("", "-wal", "-shm"):
            src = legacy_dir / f"polily.db{suffix}"
            if src.exists():
                dst = new_dir / f"polily.db{suffix}"
                shutil.copy2(src, dst)
                copied_files.append(dst)
                logger.info("Copied legacy %s → %s", src, dst)
    except OSError:
        # Partial copy — cleanup so next launch's needs_migration()
        # correctly returns True (new path is empty again).
        for f in copied_files:
            with contextlib.suppress(OSError):
                f.unlink()
        raise

    # Mark legacy dir as migrated so we don't re-prompt.
    marker = legacy_dir / MARKER_FILENAME
    marker.write_text("Migrated by polily v0.11.0\n")


def prompt_and_migrate() -> bool:
    """Interactive prompt + migration. Returns True if the user accepted
    and migration succeeded; False otherwise (no legacy / declined /
    error).

    Prints to stderr (so it doesn't pollute stdout if the user piped
    polily output). Uses ``builtins.input`` for the y/n — Textual TUI
    must NOT have started yet when this runs.

    Caller is responsible for invoking this BEFORE entering the Textual
    UI (which takes over the terminal) and BEFORE constructing
    ``PolilyService`` (which would create an empty new file at
    ``paths.db_path()`` and defeat the migration prompt's "new path is
    empty" check).
    """
    if not needs_migration():
        return False

    legacy_db = paths.legacy_db_path()
    new_db = paths.db_path()
    sys.stderr.write(
        f"\n[polily v0.11.0] 检测到旧版数据库:\n"
        f"  {legacy_db}\n"
        f"polily 现在将数据保存到:\n"
        f"  {new_db}\n"
        f"是否复制旧数据到新位置? [Y/n]: "
    )
    sys.stderr.flush()

    try:
        answer = input("").strip().lower()
    except EOFError:
        # No tty (piped or scripted). Skip + mark.
        answer = "n"

    if answer in ("", "y", "yes"):
        try:
            perform_migration()
            sys.stderr.write(f"已复制. 新数据位置: {new_db}\n")
            sys.stderr.flush()
            return True
        except OSError as e:
            sys.stderr.write(
                f"迁移失败: {e}\n请手动复制 {legacy_db} → {new_db}\n"
            )
            sys.stderr.flush()
            return False
    else:
        # User declined. Place marker so we don't re-prompt. Best effort —
        # if the legacy dir is read-only we'll re-prompt next launch, which
        # is fine.
        marker = paths.legacy_data_dir() / MARKER_FILENAME
        with contextlib.suppress(OSError):
            marker.write_text("User declined migration\n")
        sys.stderr.write(
            f"已跳过迁移. polily 将使用空的新数据库.\n"
            f"如需手动迁移: cp {legacy_db}* {new_db.parent}/\n"
        )
        sys.stderr.flush()
        return False
