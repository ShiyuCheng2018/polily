#!/usr/bin/env python3
"""Generate manual.md (polily) + SKILL.md (polily-plugin) from skill_sources/core/*.md.

Run from polily repo root:

    python scripts/generate_skills.py                       # default --plugin-repo ../polily-plugin
    python scripts/generate_skills.py --plugin-repo PATH    # explicit path
    python scripts/generate_skills.py --check               # dry-run; exit 1 on drift

The generator is deterministic given identical sources (timestamp/version
header lines are stripped before drift comparison so --check works under git).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "polily" / "agents" / "skill_sources" / "core"
MANUAL_TARGET = REPO_ROOT / "polily" / "agents" / "manual.md"


def _git_short_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "UNKNOWN"


def _polily_version() -> str:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        import polily
        return polily.__version__
    except Exception:
        return "UNKNOWN"


def _make_header() -> str:
    return (
        "<!--\n"
        "GENERATED FILE — DO NOT EDIT\n"
        f"Source: polily v{_polily_version()} (git {_git_short_sha()})\n"
        f"Generated at: {datetime.now(UTC).isoformat()}\n"
        "Generator: scripts/generate_skills.py\n"
        "To modify: edit polily/agents/skill_sources/core/*.md, then re-run.\n"
        "-->"
    )


def _make_skill_frontmatter() -> str:
    return (
        "---\n"
        "name: polily\n"
        "description: |\n"
        "  Use when working with polily prediction-market analysis tool. "
        "Provides DB schema, data freshness rules, polily mechanics, and file path "
        "conventions. Activates on polily mention, polymarket monitoring, or polily.db queries.\n"
        "---\n"
    )


def _concat_sources() -> str:
    files = sorted(SOURCES_DIR.glob("*.md"))
    return "\n\n".join(f.read_text(encoding="utf-8").rstrip() for f in files)


def _strip_volatile(text: str) -> str:
    """Remove lines that vary across runs (timestamp / git sha) for drift comparison."""
    text = re.sub(r"^Source: polily v.*$", "Source: <stripped>", text, flags=re.M)
    text = re.sub(r"^Generated at: .*$", "Generated at: <stripped>", text, flags=re.M)
    return text


def _build_manual_content(body: str) -> str:
    return f"{_make_header()}\n\n# Polily Reference Manual\n\n{body}\n"


def _build_skill_content(body: str) -> str:
    return f"{_make_skill_frontmatter()}\n{_make_header()}\n\n{body}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-repo", default=str(REPO_ROOT.parent / "polily-plugin"))
    ap.add_argument("--check", action="store_true", help="Dry-run; exit 1 on drift.")
    args = ap.parse_args()

    body = _concat_sources()
    manual_content = _build_manual_content(body)
    skill_target = Path(args.plugin_repo) / "skills" / "polily" / "SKILL.md"
    skill_content = _build_skill_content(body)

    if args.check:
        existing_manual = MANUAL_TARGET.read_text() if MANUAL_TARGET.exists() else ""
        if _strip_volatile(existing_manual) != _strip_volatile(manual_content):
            print("DRIFT: polily/agents/manual.md does not match skill_sources/core/", file=sys.stderr)
            return 1
        if skill_target.exists():
            existing_skill = skill_target.read_text()
            if _strip_volatile(existing_skill) != _strip_volatile(skill_content):
                print(f"DRIFT: {skill_target} does not match skill_sources/core/", file=sys.stderr)
                return 1
        return 0

    MANUAL_TARGET.parent.mkdir(parents=True, exist_ok=True)
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_TARGET.write_text(manual_content, encoding="utf-8")
    skill_target.write_text(skill_content, encoding="utf-8")
    print(f"✓ Wrote {MANUAL_TARGET.relative_to(REPO_ROOT)}")
    print(f"✓ Wrote {skill_target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
