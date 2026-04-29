"""Generate a read-only yaml snapshot of the running PolilyConfig.

Per design §2.3 + §4.4 — yaml is no longer a config input source. It's
overwritten on every polily startup to mirror db.config + ephemerals
(api.user_agent), and serves as a human-readable debugging snapshot.
"""
from __future__ import annotations

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
    target.write_text(content, encoding="utf-8")
