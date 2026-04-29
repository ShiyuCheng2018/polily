"""CI gate: every territory A key_path must have a markdown description.

Per design §6.3. If you add a knob to PolilyConfig.movement / .scoring /
.mispricing / .wallet, update the corresponding config_docs/*.md file
with a `## <key_path>` section.
"""
from __future__ import annotations

from polily.core.config import PolilyConfig
from polily.core.config_docs import load_all
from polily.core.config_store import (
    _flatten_pydantic,
    is_territory_a,
)


def _territory_a_keys() -> set[str]:
    flat = _flatten_pydantic(PolilyConfig())
    return {key for key in flat if is_territory_a(key)}


def test_all_territory_a_keys_have_markdown_description():
    """Every TUI-editable knob must have a `## <key_path>` section in
    config_docs/*.md. Catches drift where a new field is added but
    nobody updates the docs.

    Note: HIDDEN_IN_TUI fields (api.* / tui.* / ai.* / archiving.*) and
    EPHEMERAL_FIELDS (api.user_agent) are exempt — they're never shown
    to users via Edit modal.
    """
    pydantic_keys = _territory_a_keys()
    markdown_keys = set(load_all().keys())

    missing = pydantic_keys - markdown_keys
    extra = markdown_keys - pydantic_keys

    assert not missing, (
        f"{len(missing)} territory A knob(s) lack markdown description:\n"
        + "\n".join(f"  - {k}" for k in sorted(missing))
        + "\n\nFix: add `## {key}` section to the appropriate config_docs/*.md."
    )

    assert not extra, (
        f"{len(extra)} markdown section(s) reference key_paths that are NOT "
        f"in PolilyConfig:\n"
        + "\n".join(f"  - {k}" for k in sorted(extra))
        + "\n\nFix: delete the markdown section, or fix the typo in `## key_path`."
    )


def test_territory_a_count_matches_design_doc():
    """Pin the territory A count to 40 per design §3.2.

    If this fails:
    1. The schema changed (new knob added or removed) — update design doc + this test
    2. The whitelist prefixes need adjusting (territory A scope changed)
    """
    assert len(_territory_a_keys()) == 40
