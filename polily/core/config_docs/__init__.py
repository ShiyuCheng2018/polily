"""Markdown documentation for config knobs.

Per design §6 — each UI section has a markdown file with `## <key_path>`
headings; the Edit modal renders the matching section as the help text.
"""
from polily.core.config_docs._loader import load_all

__all__ = ["load_all"]
