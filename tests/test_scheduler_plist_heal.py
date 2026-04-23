"""Stale-plist auto-heal: ensure_daemon_running must regenerate + reload
the plist when on-disk content no longer matches what the current code
would generate (covers the v0.9.0 scanner -> polily package rename case
where the pre-upgrade plist still points at `-m scanner.cli`)."""
from __future__ import annotations

import sys
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


def test_claude_cli_only_drift_does_not_reload_daemon(tmp_plist_path):
    """If the only plist difference is POLILY_CLAUDE_CLI (user switched
    nvm versions), write the new bytes but do NOT unload+load — that
    would SIGTERM any in-flight narrator analysis.

    Next deliberate `polily scheduler restart` picks up the new path.
    Meanwhile BaseAgent's dangling-path check handles the stale-env
    case at narrator-invocation time.
    """
    # Seed disk with a "v1" plist containing path A
    v1 = sched.generate_launchd_plist(
        working_dir=str(tmp_plist_path.parent),
        claude_cli="/old/nvm/bin/claude",
    )
    tmp_plist_path.write_bytes(v1)

    # Now make the generator return "v2" with path B — only difference
    # vs on-disk is the POLILY_CLAUDE_CLI value.
    import polily.daemon.scheduler as _s
    original_generate = _s.generate_launchd_plist

    def fake_generate(**kwargs):
        kwargs.setdefault("claude_cli", "/new/nvm/bin/claude")
        return original_generate(**kwargs)

    with patch.object(_s, "generate_launchd_plist", side_effect=fake_generate), \
         patch.object(_s, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        started = _s.ensure_daemon_running()

    # New plist bytes written to disk
    assert b"/new/nvm/bin/claude" in tmp_plist_path.read_bytes()
    # But NO launchctl unload/load calls issued — running daemon untouched
    subprocess_calls = [str(c.args) for c in mock_run.call_args_list]
    assert not any("unload" in c for c in subprocess_calls), subprocess_calls
    assert not any("load" in c for c in subprocess_calls), subprocess_calls
    # Report "not started" — nothing changed for the running daemon
    assert started is False


def test_non_claude_drift_still_reloads(tmp_plist_path):
    """Control case: if anything OTHER than POLILY_CLAUDE_CLI differs
    (package rename, PATH change, WorkingDirectory change), the
    existing unload+load behavior still fires. Keeps the v0.9.0 auto-heal
    contract intact."""
    tmp_plist_path.write_bytes(b"<plist>STALE CONTENT with scanner.cli</plist>")
    with patch.object(sched, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        started = sched.ensure_daemon_running()

    assert started is True
    subprocess_calls = [str(c.args) for c in mock_run.call_args_list]
    assert any("unload" in c for c in subprocess_calls)
    assert any("load" in c for c in subprocess_calls)


def test_unparsable_old_plist_forces_reload(tmp_plist_path):
    """If the on-disk plist is malformed / truncated / user-edited garbage,
    `_only_claude_cli_diff` returns False from the except branch and we
    reload. This is the safety fallback — don't skip reload on data we
    can't interpret."""
    tmp_plist_path.write_bytes(b"\x00\x01\x02 not a plist at all")
    with patch.object(sched, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        started = sched.ensure_daemon_running()

    assert started is True, "unparsable plist must force a reload"
    subprocess_calls = [str(c.args) for c in mock_run.call_args_list]
    assert any("unload" in c for c in subprocess_calls)
    assert any("load" in c for c in subprocess_calls)


def test_v090_plist_migration_triggers_reload(tmp_plist_path):
    """Upgrade path every existing v0.9.0 user hits: on-disk plist has
    no POLILY_CLAUDE_CLI key; desired plist has one. This is NOT a
    claude-only drift (the key is being added, not swapped), so we MUST
    reload — otherwise the running v0.9.0 daemon keeps using bare
    `claude` from its stripped PATH and continues failing.

    This is the single most-hit migration scenario; if this test is
    wrong, every v0.9.0 user gets a silent no-op upgrade.
    """
    import plistlib
    # v0.9.0-era plist: has PATH but no POLILY_CLAUDE_CLI
    v090_plist = plistlib.dumps({
        "Label": sched.PLIST_LABEL,
        "ProgramArguments": [sys.executable, "-m", "polily.cli", "scheduler", "run"],
        "WorkingDirectory": str(tmp_plist_path.parent),
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "EnvironmentVariables": {"PATH": "/usr/local/bin:/usr/bin:/bin"},
    })
    tmp_plist_path.write_bytes(v090_plist)

    # v0.9.1 desired plist: same shape + POLILY_CLAUDE_CLI
    import polily.daemon.scheduler as _s
    original_generate = _s.generate_launchd_plist

    def fake_generate(**kwargs):
        kwargs.setdefault("claude_cli", "/Users/x/.nvm/bin/claude")
        return original_generate(**kwargs)

    with patch.object(_s, "generate_launchd_plist", side_effect=fake_generate), \
         patch.object(_s, "is_daemon_running", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        started = _s.ensure_daemon_running()

    assert started is True, "v0.9.0 → v0.9.1 migration MUST reload"
    subprocess_calls = [str(c.args) for c in mock_run.call_args_list]
    assert any("unload" in c for c in subprocess_calls)
    assert any("load" in c for c in subprocess_calls)
    # And the new bytes actually contain the env var
    assert b"POLILY_CLAUDE_CLI" in tmp_plist_path.read_bytes()
