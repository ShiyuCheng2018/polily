"""Generate a read-only yaml snapshot of the running PolilyConfig.

Per design §2.3 + §4.4 — yaml is no longer a config input source. It's
overwritten on every polily startup to mirror db.config + ephemerals
(api.user_agent), and serves as a human-readable debugging snapshot.
"""
from __future__ import annotations

import contextlib
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import yaml

from polily.core.config import PolilyConfig

HEADER_TEMPLATE = """\
# ══════════════════════════════════════════════════════════════════
# READ ONLY — 此文件由 polily 从数据库自动生成
# ══════════════════════════════════════════════════════════════════
#
# 每次 polily 启动都会重新生成，手动修改会丢失。
# 要改配置请使用：polily → ⚙ 配置
#
# 生成时间: {generated_at}
# polily 版本: {polily_version}
# ══════════════════════════════════════════════════════════════════

"""


def generate_yaml(config: PolilyConfig, target: Path) -> None:
    """Dump PolilyConfig to yaml, overwriting target file.

    Per design §4.4. `config.model_dump()` includes api.user_agent (just
    computed by default_factory) so the yaml snapshot reflects the
    currently-running User-Agent — even though api.user_agent is NOT in
    db.config (EPHEMERAL_FIELDS).

    SF2 (v0.10.0): writes are atomic via tempfile + os.replace. Without
    this, a crash mid-write or two racing startup paths (TUI + daemon
    both regen) could leave a half-truncated yaml. `Path.replace` is
    atomic on POSIX and Windows for Python 3.3+; if the rename fails,
    the .tmp file is unlinked and the original target is unchanged.
    """
    from polily import __version__

    body = yaml.safe_dump(
        config.model_dump(),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,  # preserve Pydantic field declaration order
    )
    content = HEADER_TEMPLATE.format(
        generated_at=datetime.now(UTC).isoformat(),
        polily_version=__version__,
    ) + body

    # Per-writer unique tmp suffix avoids the case where two concurrent
    # writers share the same .tmp path: writer A finishes its rename
    # consuming the .tmp file just as writer B finishes write_text and
    # tries to rename — B would FileNotFoundError. PID + thread id is
    # enough; we don't need cryptographic uniqueness here.
    tmp_suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
    tmp = target.with_suffix(target.suffix + tmp_suffix)
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
    except Exception:
        # Best-effort cleanup. `missing_ok=True` ensures we don't mask
        # the original exception with a FileNotFoundError if .tmp never
        # got written (e.g., disk full on the write_text call).
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
