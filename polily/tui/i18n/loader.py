"""Catalog file loader: scan a directory of `<lang>.json` files."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_catalogs(directory: Path) -> dict[str, dict[str, str]]:
    """Load every `*.json` in `directory` as a catalog.

    File name (without `.json`) is the language code.
    Malformed files are skipped with a warning, never raising.
    Missing directory returns an empty dict.

    Returns: {lang_code: {key: translation}}
    """
    if not directory.exists() or not directory.is_dir():
        return {}

    catalogs: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        lang = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("i18n: skipping malformed catalog %s: %s", path, e)
            continue
        except OSError as e:
            logger.warning("i18n: skipping unreadable catalog %s: %s", path, e)
            continue
        if not isinstance(data, dict):
            logger.warning("i18n: catalog %s is not a dict (got %s); skipping", path, type(data).__name__)
            continue
        # Coerce all values to str (defensive — JSON might carry numbers/null on author error).
        cleaned: dict[str, str] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                logger.warning("i18n: catalog %s has non-str key %r; skipping entry", path, k)
                continue
            cleaned[k] = str(v) if not isinstance(v, str) else v
        catalogs[lang] = cleaned
    return catalogs
