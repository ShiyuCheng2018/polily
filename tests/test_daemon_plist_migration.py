"""Whis B2 — legacy plist with --config arg gets migrated on startup."""
from __future__ import annotations


def test_legacy_plist_with_config_flag_gets_rewritten(tmp_path, monkeypatch):
    """User upgrading from v0.9.x has a plist containing --config xxx;
    on next ensure_daemon_running call, plist gets rewritten without
    --config so daemon can launch successfully under v0.10.0."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    legacy_xml = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
  <key>Label</key><string>com.polily.scheduler</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/polily</string>
    <string>scheduler</string>
    <string>run</string>
    <string>--config</string>
    <string>/Users/test/config.yaml</string>
  </array>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""
    plist_path.write_text(legacy_xml, encoding="utf-8")

    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    # Avoid actually invoking launchctl
    invoked = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, *a, **kw: invoked.append(cmd) or type("R", (), {"returncode": 0})(),
    )

    from polily.daemon.scheduler import _migrate_legacy_plist
    migrated = _migrate_legacy_plist()

    assert migrated is True
    new_xml = plist_path.read_text(encoding="utf-8")
    assert "--config" not in new_xml
    assert "/Users/test/config.yaml" not in new_xml
    # Should have triggered launchctl unload + load
    assert any("unload" in str(c) for c in invoked)
    assert any("load" in str(c) for c in invoked)


def test_modern_plist_without_config_is_not_touched(tmp_path, monkeypatch):
    """Idempotent — a v0.10.0+ plist (no --config) is left alone."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    modern_xml = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
  <key>Label</key><string>com.polily.scheduler</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/polily</string>
    <string>scheduler</string>
    <string>run</string>
  </array>
</dict>
</plist>
"""
    plist_path.write_text(modern_xml, encoding="utf-8")

    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, *a, **kw: type("R", (), {"returncode": 0})(),
    )

    from polily.daemon.scheduler import _migrate_legacy_plist
    migrated = _migrate_legacy_plist()
    assert migrated is False  # nothing to do
    # Plist content unchanged
    assert plist_path.read_text(encoding="utf-8") == modern_xml


def test_missing_plist_skips_migration(tmp_path, monkeypatch):
    """Fresh install — no plist yet, migration is a no-op."""
    plist_path = tmp_path / "com.polily.scheduler.plist"  # doesn't exist
    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)

    from polily.daemon.scheduler import _migrate_legacy_plist
    assert _migrate_legacy_plist() is False
