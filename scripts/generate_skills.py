#!/usr/bin/env python3
"""Generate manual.md (polily) + SKILL.md (polily-plugin) from skill_sources/core/*.md.

Run from polily repo root:

    python scripts/generate_skills.py                       # default --plugin-repo ../polily-plugin
    python scripts/generate_skills.py --plugin-repo PATH    # explicit path
    python scripts/generate_skills.py --check               # dry-run; exit 1 on drift

The generator is deterministic given identical sources (timestamp/version
header lines are stripped before drift comparison so --check works under git).

## Audience tagging (v0.12.0+)

Source files in `polily/agents/skill_sources/core/*.md` may contain
audience-scoped blocks that are included in only one of the two outputs:

    <!-- internal-only -->
    Content appears in manual.md only (polily's internal agent prompt).
    Use for: agent persona ("You are..."), per-call YAML protocol,
    strategy fallback flow, maintainer-tooling references.
    <!-- /internal-only -->

    <!-- external-only -->
    Content appears in SKILL.md only (Claude Code marketplace plugin).
    Use for: "About Polily" framing, codebase pointers, dev recipes,
    anything aimed at developers working ON polily (not the agent
    running as polily).
    <!-- /external-only -->

Content NOT wrapped in either tag appears in BOTH outputs (this is the
default — most of §2-§5 is shared reference material). Tags can be
inline (one-paragraph parenthetical) or block-level (multi-paragraph
section). The trailing newline after a closing tag is consumed so
removal doesn't leave double blank lines.

The single-source-of-truth pattern is preserved: every byte of every
output is generated from these files. To update either output, edit
the source.
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

# Audience block regexes. `re.DOTALL` so `.` matches newlines (multi-line blocks).
# Leading ` ?` absorbs one optional preceding space — handles the inline
# mid-line case (e.g. `text. <!-- internal-only -->note<!-- /internal-only -->
# more text` becoming `text. more text` instead of `text.  more text` with
# a double space). Block-level tags at line start have a preceding `\n`, not
# space, so the leading ` ?` matches nothing there (safe).
#
# Trailing `\n?` was tempting but turned out to break the case of an inline
# tag at end of line followed by a blank line (e.g. §4 line 36):
#     - **`Read`** — local file system <!-- /internal-only -->
#                                                             ← blank line
#     Cost is non-trivial...
# Source bytes: `... -->\n\nCost ...` (newline ending the bullet, then
# blank line, then paragraph). `\n?` would eat one of the two `\n`s,
# collapsing the blank line and merging the bullet with the next paragraph
# (or worse: making the paragraph a lazy continuation of the list item).
#
# Solution: don't eat any newline in the tag-strip phase. Let
# `_normalize_whitespace` collapse the resulting `\n{3,}` artifacts at
# block-level boundaries uniformly. One pass at the end instead of trying
# to handle every case in the regex.
_INTERNAL_BLOCK = re.compile(
    r" ?<!-- internal-only -->.*?<!-- /internal-only -->",
    re.DOTALL,
)
_EXTERNAL_BLOCK = re.compile(
    r" ?<!-- external-only -->.*?<!-- /external-only -->",
    re.DOTALL,
)
# Same-audience wrapper tags: keep content but strip the bare markers.
# Same `\n?` rationale as the block regexes above — let normalize handle
# blank-line collapse.
_INTERNAL_TAG = re.compile(r"<!-- /?internal-only -->")
_EXTERNAL_TAG = re.compile(r"<!-- /?external-only -->")


def _filter_audience(text: str, target: str) -> str:
    """Strip blocks not intended for ``target`` audience.

    Args:
        text: source markdown body (may contain audience-tagged blocks)
        target: ``"internal"`` (manual.md) or ``"external"`` (SKILL.md)

    Returns:
        Text with foreign-audience blocks removed AND same-audience wrapper
        tags stripped (content preserved). Untagged content (the default)
        appears for both audiences verbatim.

    Two-pass strategy: first drop foreign-audience blocks (content + tags),
    then strip the same-audience wrapper tags so the surviving content
    reads cleanly without leftover `<!-- internal-only -->` markers.
    """
    if target == "internal":
        text = _EXTERNAL_BLOCK.sub("", text)  # drop external-only entirely
        text = _INTERNAL_TAG.sub("", text)    # strip wrappers, keep content
        return _normalize_whitespace(text)
    if target == "external":
        text = _INTERNAL_BLOCK.sub("", text)  # drop internal-only entirely
        text = _EXTERNAL_TAG.sub("", text)    # strip wrappers, keep content
        return _normalize_whitespace(text)
    raise ValueError(f"target must be 'internal' or 'external', got {target!r}")


def _normalize_whitespace(text: str) -> str:
    """Clean up artifacts left by inline / block audience-tag stripping.

    Two passes:
      1. Strip trailing whitespace on every line. Inline tag strips like
         ``text <!-- internal-only -->...<!-- /internal-only -->`` leave a
         stray space at end of line; table cells like
         ``... analysis). <!-- internal-only -->note<!-- /... --> |``
         leave a double-space before the cell separator. Both render fine
         but lint as trailing whitespace and look untidy.
      2. Collapse runs of 3+ consecutive newlines to 2 (single blank line).
         Block-level tag strips leave double blank lines where the source
         had a single blank line surrounding the tag block.

    Both passes are idempotent on already-clean input.
    """
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)  # trailing whitespace per line
    text = re.sub(r"\n{3,}", "\n\n", text)  # max one blank line between paragraphs
    return text


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
    # Two-use-case framing:
    #   1. Chat consultation — polily user asks follow-up questions about
    #      their TUI analysis, positions, or polily's reasoning framework
    #      ("explain why edge is thin", "what's my biggest position")
    #   2. Development — extending polily code, querying polily.db schema,
    #      debugging the NarrativeWriter agent or movement pipeline
    # Negative trigger keeps the skill scoped — generic "what is Polymarket"
    # questions should not activate.
    return (
        "---\n"
        "name: polily\n"
        "description: |\n"
        "  Use when the user references polily — either asking follow-up questions about "
        "a polily-generated analysis (interpreting structure_score, edge claims, friction "
        "breakdowns, position guidance, why polily said what it said), querying polily's "
        "local state (positions, wallet, past analyses in polily.db), or working ON the "
        "polily codebase (editing polily/* source, debugging the NarrativeWriter agent, "
        "extending the scoring/movement pipeline). Provides DB schema, daemon mechanics, "
        "file paths, codebase entry points, and a runtime-lookup procedure for polily's "
        "analytical methodology. "
        "Do NOT activate for generic Polymarket questions unrelated to polily.\n"
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
    # .strip() both ends so:
    # - leading `\n` from audience-block strips at file start (e.g. when
    #   01_persona.md begins with <!-- internal-only -->\n## 1. Who You Are)
    #   doesn't add extra blank lines between the header and §1
    # - trailing `\n` artifacts at file end don't compound with the format
    #   string's trailing `\n` to produce `\n\n\n`.
    filtered = _filter_audience(body, "internal").strip()
    return f"{_make_header()}\n\n# Polily Reference Manual\n\n{filtered}\n"


def _build_skill_content(body: str) -> str:
    filtered = _filter_audience(body, "external").strip()
    return f"{_make_skill_frontmatter()}\n{_make_header()}\n\n{filtered}\n"


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
