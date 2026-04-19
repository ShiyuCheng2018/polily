"""Post-migration smoke: no caller still imports or invokes the retired symbol.

The symbol name is split across string concatenation, and this file is
excluded from its own grep, so the smoke test can't match itself.
"""
import subprocess

_SYMBOL = "update_next_" + "check_at"


def test_no_caller_imports_retired_symbol():
    result = subprocess.run(
        [
            "grep", "-rn",
            "--include=*.py",
            "--exclude=test_update_next_check_at_removal.py",
            _SYMBOL, "scanner/", "tests/",
        ],
        capture_output=True, text=True,
    )
    # Allow grep exit 1 (no matches) as success.
    # Exit 0 means matches found; exit 1 means none. Anything else is a tool error.
    assert result.returncode == 1, (
        f"{_SYMBOL} still referenced:\n{result.stdout}"
    )


def test_monitor_store_does_not_expose_retired_symbol():
    from scanner.core import monitor_store
    assert not hasattr(monitor_store, _SYMBOL)
