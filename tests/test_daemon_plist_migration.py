"""Whis B2 — legacy plist with --config arg gets migrated on startup."""
from __future__ import annotations

import subprocess

import pytest


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
    # SF7 platform guard: pretend Darwin + launchctl present so the
    # migration body actually runs on Linux CI (otherwise short-circuits).
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/launchctl")
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
    # SF7 platform guard: pretend Darwin + launchctl present.
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/launchctl")
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


def test_migration_load_failure_propagates(tmp_path, monkeypatch):
    """If launchctl load fails after the rewrite, error propagates so the
    daemon-startup caller (ensure_daemon_running) can react. Silent failure
    here would defeat B2's purpose — daemon would keep crash-looping with
    legacy plist until reboot."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    plist_path.write_text(
        '<?xml version="1.0"?><plist><dict>'
        "<key>ProgramArguments</key><array>"
        "<string>polily</string><string>scheduler</string><string>run</string>"
        "<string>--config</string><string>/x.yaml</string>"
        "</array></dict></plist>",
        encoding="utf-8",
    )

    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    # SF7 platform guard: pretend Darwin + launchctl present.
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/launchctl")

    def fake_run(cmd, *a, **kw):
        # unload succeeds (rc=0); load fails. check=True on the load call
        # turns the non-zero rc into a real CalledProcessError that the
        # migration code is expected to propagate.
        if "load" in cmd:
            raise subprocess.CalledProcessError(
                returncode=1, cmd=cmd, stderr="bad plist",
            )
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)

    from polily.daemon.scheduler import _migrate_legacy_plist
    with pytest.raises(subprocess.CalledProcessError):
        _migrate_legacy_plist()


def test_migration_no_op_on_non_darwin(tmp_path, monkeypatch):
    """SF7 (v0.10.0) — `_migrate_legacy_plist` must be a no-op on Linux /
    other non-Darwin platforms. CI runs on Linux; before this guard,
    `subprocess.run(['launchctl', ...])` raised FileNotFoundError when
    launchctl wasn't on PATH, propagating out of every daemon-startup code
    path that called the helper."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    # Even with a legacy plist on disk, non-Darwin must skip cleanly.
    plist_path.write_text(
        '<?xml version="1.0"?><plist><dict>'
        "<key>ProgramArguments</key><array>"
        "<string>polily</string><string>scheduler</string><string>run</string>"
        "<string>--config</string><string>/x.yaml</string>"
        "</array></dict></plist>",
        encoding="utf-8",
    )
    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    monkeypatch.setattr("sys.platform", "linux")

    # subprocess.run must NEVER be called — if it is, the test is asserting
    # the wrong behavior (the guard should skip *before* any subprocess work).
    def fail_subprocess_run(*a, **kw):
        raise AssertionError(
            "subprocess.run was called on non-Darwin platform — "
            "the SF7 guard should have already returned False.",
        )

    monkeypatch.setattr("subprocess.run", fail_subprocess_run)

    from polily.daemon.scheduler import _migrate_legacy_plist
    assert _migrate_legacy_plist() is False
    # Plist file should still be on disk untouched
    assert "--config" in plist_path.read_text(encoding="utf-8")


def test_migration_no_op_when_launchctl_not_on_path(tmp_path, monkeypatch):
    """SF7 — even on Darwin, if `shutil.which('launchctl')` returns None
    (extreme fringe case: `/bin` stripped from PATH, or sandboxed env),
    the helper must still skip gracefully rather than blowing up with
    FileNotFoundError when subprocess.run tries to exec launchctl."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    plist_path.write_text(
        '<?xml version="1.0"?><plist><dict>'
        "<key>ProgramArguments</key><array>"
        "<string>polily</string><string>scheduler</string><string>run</string>"
        "<string>--config</string><string>/x.yaml</string>"
        "</array></dict></plist>",
        encoding="utf-8",
    )
    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    monkeypatch.setattr("sys.platform", "darwin")
    # Force which() to report launchctl missing
    monkeypatch.setattr("shutil.which", lambda name: None)

    def fail_subprocess_run(*a, **kw):
        raise AssertionError("subprocess.run called despite missing launchctl")

    monkeypatch.setattr("subprocess.run", fail_subprocess_run)

    from polily.daemon.scheduler import _migrate_legacy_plist
    assert _migrate_legacy_plist() is False


def test_migration_called_twice_second_call_is_noop(tmp_path, monkeypatch):
    """First call rewrites legacy plist; second call sees modern plist
    and returns False without invoking launchctl."""
    plist_path = tmp_path / "com.polily.scheduler.plist"
    plist_path.write_text(
        '<?xml version="1.0"?><plist><dict>'
        "<key>ProgramArguments</key><array>"
        "<string>polily</string><string>scheduler</string><string>run</string>"
        "<string>--config</string><string>/x.yaml</string>"
        "</array></dict></plist>",
        encoding="utf-8",
    )

    monkeypatch.setattr("polily.daemon.scheduler.PLIST_PATH", plist_path)
    # SF7 platform guard: pretend Darwin + launchctl present.
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/launchctl")
    invocations = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, *a, **kw: invocations.append(cmd)
        or type("R", (), {"returncode": 0, "stderr": ""})(),
    )

    from polily.daemon.scheduler import _migrate_legacy_plist
    assert _migrate_legacy_plist() is True   # first call: rewrites
    invocations_after_first = len(invocations)
    assert _migrate_legacy_plist() is False  # second call: no-op
    # No further launchctl calls on second invocation
    assert len(invocations) == invocations_after_first
