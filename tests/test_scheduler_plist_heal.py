"""Stale-plist auto-heal: ensure_daemon_running must regenerate + reload
the plist when on-disk content no longer matches what the current code
would generate (covers the v0.9.0 scanner -> polily package rename case
where the pre-upgrade plist still points at `-m scanner.cli`)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import polily.daemon.scheduler as sched


@pytest.fixture(autouse=True)
def _neutralize_which(monkeypatch):
    """Force `shutil.which('claude')` to return None in scheduler plist
    tests. Individual tests that need a resolved path pass
    `claude_cli="/explicit/path"` to `generate_launchd_plist` instead.

    Rationale: without this, tests embed the dev's actual nvm path in
    generated plist bytes, coupling CI behavior to local install state.

    Patches via string `"shutil.which"` (not `sched.shutil.which`) so
    it's robust to whether scheduler.py imports shutil at module level
    or via `from shutil import which`.
    """
    monkeypatch.setattr("shutil.which", lambda *_a, **_kw: None)


@pytest.fixture
def tmp_plist_path(tmp_path, monkeypatch):
    path = tmp_path / "com.polily.scheduler.plist"
    monkeypatch.setattr(sched, "PLIST_PATH", path)
    # Align Path.cwd() with tmp_path so generate_launchd_plist produces
    # deterministic WorkingDirectory content across the fixture + test.
    monkeypatch.chdir(tmp_path)
    return path


def test_stale_plist_content_triggers_regen(tmp_plist_path):
    """If the on-disk plist differs from what the current code generates
    (e.g. because the user upgraded across a package rename), ensure
    ensure_daemon_running writes the fresh plist and issues launchctl
    unload+load regardless of whether launchctl thinks a daemon is running."""
    tmp_plist_path.write_bytes(b"<plist>STALE CONTENT with scanner.cli</plist>")

    with patch.object(sched, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        started = sched.ensure_daemon_running()

    assert started is True, "must report started after regen+reload"
    assert b"scanner.cli" not in tmp_plist_path.read_bytes()
    assert b"polily.cli" in tmp_plist_path.read_bytes()
    # Both unload + load got called (order doesn't matter for this assertion).
    subprocess_calls = [str(c.args) for c in mock_run.call_args_list]
    assert any("unload" in c for c in subprocess_calls)
    assert any("load" in c for c in subprocess_calls)


def test_matching_plist_skips_regen(tmp_plist_path):
    """If the on-disk plist already matches what the current code would
    generate AND daemon is running, ensure_daemon_running bails out
    without touching launchctl (normal happy path)."""
    fresh_plist = sched.generate_launchd_plist(working_dir=str(tmp_plist_path.parent))
    tmp_plist_path.write_bytes(fresh_plist)

    with patch.object(sched, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        started = sched.ensure_daemon_running()

    assert started is False
    assert mock_run.call_count == 0, "no launchctl calls when plist matches + running"


def test_plist_embeds_injected_claude_cli(tmp_path):
    """When caller passes claude_cli, plist EnvironmentVariables must include
    POLILY_CLAUDE_CLI=<that path>. This is the core contract that lets the
    launchd-spawned daemon find claude CLI no matter where nvm/brew put it."""
    fake_claude = "/opt/homebrew/bin/claude"
    plist_bytes = sched.generate_launchd_plist(
        working_dir=str(tmp_path),
        claude_cli=fake_claude,
    )
    # plistlib round-trip so we assert on parsed structure, not raw XML
    import plistlib
    parsed = plistlib.loads(plist_bytes)
    env = parsed["EnvironmentVariables"]
    # Exact key set — future code adding an env key should force a
    # deliberate test update, not silently change the contract.
    assert set(env.keys()) == {"PATH", "POLILY_CLAUDE_CLI"}
    assert env["POLILY_CLAUDE_CLI"] == fake_claude
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_plist_omits_claude_cli_when_unresolved(tmp_path):
    """When shutil.which returns None (claude not installed yet — autouse
    fixture mocks this), plist must still generate successfully but without
    POLILY_CLAUDE_CLI. BaseAgent falls back to bare 'claude' at runtime;
    the narrator job fails with a sensible error in scan_logs. This keeps
    first-run onboarding from crashing the daemon before user installs claude."""
    plist_bytes = sched.generate_launchd_plist(working_dir=str(tmp_path))
    import plistlib
    parsed = plistlib.loads(plist_bytes)
    env = parsed["EnvironmentVariables"]
    assert set(env.keys()) == {"PATH"}  # no POLILY_CLAUDE_CLI, no extras


def test_plist_auto_resolves_when_caller_omits_claude_cli(tmp_path, monkeypatch):
    """Default behavior: shutil.which runs in caller's env. Override the
    module's autouse None-mock locally to return a concrete path so we
    exercise the real code path that `ensure_daemon_running` hits —
    no injection, shutil.which finds it, plist gets the env var."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name, *a, **kw: "/Users/x/.nvm/bin/claude" if name == "claude" else None,
    )
    plist_bytes = sched.generate_launchd_plist(working_dir=str(tmp_path))
    import plistlib
    parsed = plistlib.loads(plist_bytes)
    env = parsed["EnvironmentVariables"]
    assert set(env.keys()) == {"PATH", "POLILY_CLAUDE_CLI"}
    assert env["POLILY_CLAUDE_CLI"] == "/Users/x/.nvm/bin/claude"
