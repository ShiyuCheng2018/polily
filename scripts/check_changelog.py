#!/usr/bin/env python3
"""CHANGELOG release-PR validator.

Enforces the CHANGELOG discipline bits that git tags can't cover and
memory-based checklists have repeatedly failed:

1. On a release PR (dev → master), the topmost section is a versioned
   release like `## [X.Y.Z] — YYYY-MM-DD`, NOT `## [Unreleased]`. This
   catches the "forgot to rename [Unreleased]" class of mistake.

2. Every released version listed in the footer uses `releases/tag/vX.Y.Z`
   URL format, not `compare/vA...vB`. Project convention per git history
   — the compare-format `[0.9.0]` link that slipped through v0.9.0's
   release was an outlier, and the gate here prevents reintroducing it.

3. `[Unreleased]` footer link compares against the *current* top released
   version, not a stale one.

Usage:
    python scripts/check_changelog.py [CHANGELOG.md]

Exits 0 on pass, 1 on any rejection. Errors printed to stderr so CI logs
show them prominently.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Name of the long-lived dev branch `[Unreleased]` links compare against.
# One-line constant so future branch renames (e.g. dev → main) are cheap.
DEV_BRANCH_NAME = "dev"

VERSION_SECTION_RE = re.compile(
    r"^##\s+\[(?P<version>[\w.\-]+)\](?: — (?P<date>\d{4}-\d{2}-\d{2}))?",
    re.MULTILINE,
)
# Matches footer link: `[X.Y.Z]: https://.../releases/tag/vX.Y.Z` or
# `[Unreleased]: https://.../compare/vX.Y.Z...dev`.
FOOTER_LINK_RE = re.compile(
    r"^\[(?P<label>[\w.\-]+)\]:\s*(?P<url>https?://\S+)\s*$",
    re.MULTILINE,
)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _find_sections(text: str) -> list[tuple[str, str | None, int]]:
    """Return [(label, date_or_None, char_offset), ...] in document order."""
    sections: list[tuple[str, str | None, int]] = []
    for m in VERSION_SECTION_RE.finditer(text):
        sections.append((m.group("version"), m.group("date"), m.start()))
    return sections


def _find_footer_links(text: str) -> dict[str, str]:
    """Return {label: url} map from the footer."""
    return {m.group("label"): m.group("url") for m in FOOTER_LINK_RE.finditer(text)}


def validate(changelog_text: str) -> ValidationResult:
    """Validate the CHANGELOG text. Pure function — no I/O.

    Caller (CLI) wraps this with file read + stderr printing.
    """
    result = ValidationResult(ok=True)
    sections = _find_sections(changelog_text)
    links = _find_footer_links(changelog_text)

    if not sections:
        result.ok = False
        result.errors.append("No version sections found (`## [X.Y.Z]`).")
        return result

    # --- Rule 1: top non-Unreleased section must exist ---
    # If Rule 1 fails, we still run Rules 2-4 (with guards) so CI surfaces the
    # full set of violations in a single run — no need to fix+rerun iteratively.
    released_sections = [s for s in sections if s[0] != "Unreleased"]
    if not released_sections:
        result.ok = False
        result.errors.append(
            "Top of CHANGELOG is [Unreleased] with no released section "
            "below — looks like you forgot to rename [Unreleased] → [X.Y.Z] "
            "before cutting the release PR."
        )
        top_release = None  # Rules 2/3 can't reference a version we don't have
    else:
        top_release = released_sections[0][0]  # e.g. "0.9.3"

    # --- Rule 2: top released version has a matching footer link ---
    if top_release is not None and top_release not in links:
        result.ok = False
        result.errors.append(
            f"Top released version [{top_release}] has no matching footer link. "
            f"Add: `[{top_release}]: https://github.com/<owner>/<repo>/releases/tag/v{top_release}`"
        )

    # --- Rule 3: top released version's link uses tag format ---
    if top_release is not None and top_release in links:
        url = links[top_release]
        if "/releases/tag/" not in url:
            result.ok = False
            result.errors.append(
                f"[{top_release}] link uses non-tag format ({url!r}). "
                f"Project convention: `releases/tag/vX.Y.Z`. The `compare/` "
                f"format was a v0.9.0 outlier, don't reintroduce it."
            )

    # --- Rule 4: [Unreleased] footer link is REQUIRED and must point at top release ---
    unreleased_url = links.get("Unreleased")
    if unreleased_url is None:
        result.ok = False
        if top_release is not None:
            result.errors.append(
                f"[Unreleased] footer link is missing. Add: "
                f"`[Unreleased]: https://github.com/<owner>/<repo>/compare/"
                f"v{top_release}...{DEV_BRANCH_NAME}`"
            )
        else:
            result.errors.append(
                f"[Unreleased] footer link is missing. Add: "
                f"`[Unreleased]: https://github.com/<owner>/<repo>/compare/"
                f"vX.Y.Z...{DEV_BRANCH_NAME}` (replace X.Y.Z with your top "
                f"released version)."
            )
    elif top_release is not None:
        expected_fragment = f"v{top_release}...{DEV_BRANCH_NAME}"
        if expected_fragment not in unreleased_url:
            result.ok = False
            result.errors.append(
                f"[Unreleased] footer link is stale ({unreleased_url!r}). "
                f"Expected it to compare against the current top release "
                f"v{top_release} (e.g. `.../compare/v{top_release}...{DEV_BRANCH_NAME}`)."
            )

    return result


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else Path("CHANGELOG.md")
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2

    result = validate(path.read_text(encoding="utf-8"))
    if result.ok:
        print(f"✓ {path}: CHANGELOG release discipline OK")
        return 0

    print(f"✗ {path}: CHANGELOG release discipline violations:", file=sys.stderr)
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
