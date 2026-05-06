"""SF2 — yaml snapshot writes must be atomic.

Background: `generate_yaml(config, target)` previously did
`target.write_text(content)`. A crash mid-write or concurrent regen
leaves a half-truncated yaml. Realistic trigger: laptop sleep/wake
during launch, or two startup paths racing (TUI + daemon both call
`_regenerate_yaml_snapshot`).

Fix: write to `<target>.tmp`, then `os.replace` onto target. POSIX +
Win Python 3.3+ guarantee atomic rename. On exception, .tmp is cleaned
and target is untouched.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml as yaml_lib

from polily.core.config import PolilyConfig
from polily.core.config_yaml import generate_yaml


def test_happy_path_writes_yaml_and_cleans_tmp(tmp_path):
    """Normal write: target file exists, .tmp is gone afterwards."""
    target = tmp_path / "config.yaml"
    generate_yaml(PolilyConfig(), target)

    assert target.exists()
    assert "READ ONLY" in target.read_text(encoding="utf-8")
    # No .tmp leftovers — the atomic rename consumed it
    leftovers = list(tmp_path.glob("config.yaml.*.tmp"))
    assert leftovers == [], f"unexpected .tmp leftovers: {leftovers}"


def test_rename_failure_preserves_original(tmp_path, monkeypatch):
    """If os.replace raises mid-write, the original target is untouched
    and the .tmp file is cleaned up.
    """
    target = tmp_path / "config.yaml"
    # Pre-existing file we don't want clobbered
    target.write_text("# existing content — must survive\n", encoding="utf-8")
    original_bytes = target.read_bytes()

    # Force the atomic rename to fail
    real_replace = Path.replace
    def boom_replace(self, *args, **kwargs):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(Path, "replace", boom_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        generate_yaml(PolilyConfig(), target)

    # Restore so we can read disk safely
    monkeypatch.setattr(Path, "replace", real_replace)

    # Original file untouched
    assert target.read_bytes() == original_bytes
    # No .tmp leftovers — error path unlinked it
    leftovers = list(tmp_path.glob("config.yaml.*.tmp"))
    assert leftovers == [], f".tmp file leaked on error path: {leftovers}"


def test_concurrent_writers_produce_consistent_file(tmp_path):
    """Two threads racing on the same target — final file must be one
    consistent snapshot, not an interleaved hybrid of both writers' bytes.

    With the atomic rename, each writer renames a fully-written .tmp into
    place; whichever wins is the surviving content, but it's always a
    well-formed yaml that PyYAML can parse end-to-end.
    """
    target = tmp_path / "config.yaml"
    config = PolilyConfig()
    errors = []

    def worker():
        try:
            for _ in range(20):
                generate_yaml(config, target)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writers errored: {errors}"
    # File must parse as valid yaml (header is comments — strip)
    content = target.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in content.splitlines()
        if not line.lstrip().startswith("#") and line.strip()
    )
    parsed = yaml_lib.safe_load(body)
    # Must be a complete dict (not a half-truncated read)
    assert isinstance(parsed, dict)
    assert "wallet" in parsed
    assert parsed["wallet"]["starting_balance"] == 1000.0
