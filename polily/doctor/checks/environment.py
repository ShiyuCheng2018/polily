from __future__ import annotations

import os
import shutil
import sys

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity

_MIN_COLS, _MIN_ROWS = 100, 30
# Nerd Font sample glyphs (FontAwesome legacy range from tui/icons.py)
_GLYPHS = "     "


def _python_floor() -> str:
    try:
        from importlib.metadata import metadata
        return metadata("polily").get("Requires-Python", ">=3.11")
    except Exception:
        return ">=3.11"


def _python_ok(version_info, floor: str) -> tuple[bool, str]:
    """Pure: is `version_info` allowed by `floor`? Returns (ok, 'X.Y.Z').
    Extracted so tests inject a tuple instead of monkeypatching sys.version_info."""
    cur = f"{version_info[0]}.{version_info[1]}.{version_info[2]}"
    try:
        from packaging.specifiers import SpecifierSet
        return (cur in SpecifierSet(floor), cur)
    except Exception:
        return (tuple(version_info[:2]) >= (3, 11), cur)


def environment_checks(ctx: DoctorContext) -> list[CheckResult]:
    out: list[CheckResult] = []

    floor = _python_floor()
    ok, cur = _python_ok(sys.version_info, floor)
    out.append(CheckResult(
        id="env.python", title="Python version",
        severity=Severity.OK if ok else Severity.CRITICAL,
        detail=f"{cur} (requires {floor})",
        fix_hint="reinstall under Python >=3.11 (pipx install --python python3.11 polily)"
                 if not ok else None, group="environment"))

    out.append(CheckResult(
        id="env.os", title="Operating system", severity=Severity.INFO,
        detail=ctx.platform, value={"platform": ctx.platform}, group="environment"))

    cols, rows = shutil.get_terminal_size()
    is_tty = sys.stdout.isatty()
    small = cols < _MIN_COLS or rows < _MIN_ROWS
    out.append(CheckResult(
        id="env.terminal_size", title="Terminal size",
        severity=(Severity.WARN if (small and is_tty) else
                  Severity.INFO if small else Severity.OK),
        detail=f"{cols}x{rows} (min {_MIN_COLS}x{_MIN_ROWS})"
               + ("" if is_tty else ", not a TTY"),
        fix_hint="resize terminal to >=100x30 (>=120x30 recommended)"
                 if (small and is_tty) else None, group="environment"))

    font_hint = ("brew install --cask font-jetbrains-mono-nerd-font"
                 if ctx.platform == "darwin"
                 else "download a Nerd Font to ~/.local/share/fonts && fc-cache -fv")
    out.append(CheckResult(
        id="env.nerd_font", title="Nerd Font (visual check)", severity=Severity.INFO,
        detail=f"these should be icons, not boxes: {_GLYPHS}",
        verifiable=False, fix_hint=font_hint, group="environment"))

    writable = os.access(ctx.data_dir, os.W_OK)
    out.append(CheckResult(
        id="env.data_dir_writable", title="Data dir writable",
        severity=Severity.OK if writable else Severity.CRITICAL,
        detail=str(ctx.data_dir),
        fix_hint="fix permissions or set POLILY_DATA_DIR to a writable path"
                 if not writable else None, group="environment"))

    return out
