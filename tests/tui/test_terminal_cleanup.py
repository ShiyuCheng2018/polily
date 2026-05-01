"""Terminal cleanup helper — guards against os._exit leaving the user's
terminal in xterm mouse-tracking mode.

Bug R5-B: TUI exits via os._exit(0) (because claude -p spawns Node
subprocesses that survive normal Python shutdown). os._exit skips
Textual's atexit cleanup, so mouse-tracking modes (?1000/1002/1003/
1006/1015) and alt-screen (?1049) stay active in the parent terminal.
Result: every subsequent mouse move/scroll prints raw `\\x1b[<...M`
escape sequences as visible text until the user runs `reset`.

Fix: a small helper that asks the Textual driver to stop application
mode (canonical), with a fallback that writes the explicit DECRST
sequences directly to stdout when no driver is in scope.

Tests pin the contract:
  - `cleanup_terminal(app)` invokes `app._driver.stop_application_mode`
    when the driver is reachable.
  - It swallows any exception raised while restoring (we are about to
    `os._exit` regardless — never let cleanup raise).
  - The fallback path writes the disable sequences to stdout when no
    app/driver is available.
"""
from __future__ import annotations

import io
from types import SimpleNamespace


def test_cleanup_terminal_calls_driver_stop_application_mode():
    """Canonical path — when app._driver.stop_application_mode exists,
    we call it. That's the API Textual itself uses on normal shutdown."""
    from polily.tui.terminal_cleanup import cleanup_terminal

    calls = {"n": 0}

    def stop():
        calls["n"] += 1

    fake_driver = SimpleNamespace(stop_application_mode=stop)
    fake_app = SimpleNamespace(_driver=fake_driver)

    cleanup_terminal(fake_app)

    assert calls["n"] == 1


def test_cleanup_terminal_swallows_driver_exception():
    """If stop_application_mode raises (e.g. driver already torn down),
    we must NOT propagate — os._exit is about to fire and any exception
    here would be swallowed by the OS anyway, but we'd waste the chance
    to fall back to manual escape sequences."""
    from polily.tui.terminal_cleanup import cleanup_terminal

    def stop():
        raise RuntimeError("driver already stopped")

    fake_driver = SimpleNamespace(stop_application_mode=stop)
    fake_app = SimpleNamespace(_driver=fake_driver)

    # Must not raise.
    cleanup_terminal(fake_app)


def test_cleanup_terminal_falls_back_to_stdout_when_app_is_none():
    """Some exit sites (FatalConfigScreen.action_quit_app, the early
    ConfigValidationError path in run_tui's _FatalApp) don't have a
    PolilyApp instance whose ._driver is reachable. Pass `app=None`
    and we write the disable sequences directly to stdout."""
    from polily.tui.terminal_cleanup import cleanup_terminal

    buf = io.StringIO()
    cleanup_terminal(app=None, stream=buf)

    out = buf.getvalue()
    # Must disable each mouse mode that polily/Textual enables.
    assert "\x1b[?1000l" in out, "missing X10 mouse disable"
    assert "\x1b[?1002l" in out, "missing button-event mouse disable"
    assert "\x1b[?1003l" in out, "missing all-motion mouse disable"
    assert "\x1b[?1006l" in out, "missing SGR extended mouse disable"
    assert "\x1b[?1015l" in out, "missing urxvt extended mouse disable"
    # Show cursor + leave alt-screen — common Textual on-exit cleanup.
    assert "\x1b[?25h" in out, "missing show-cursor"
    assert "\x1b[?1049l" in out, "missing leave-alt-screen"


def test_cleanup_terminal_falls_back_to_stdout_when_driver_missing():
    """If app._driver is None or absent (e.g. PolilyApp in a state
    where the driver has already torn down), still write the disable
    sequences via the fallback — better redundant than leave the
    terminal corrupted."""
    from polily.tui.terminal_cleanup import cleanup_terminal

    buf = io.StringIO()
    fake_app = SimpleNamespace(_driver=None)

    cleanup_terminal(fake_app, stream=buf)

    out = buf.getvalue()
    assert "\x1b[?1000l" in out
    assert "\x1b[?1006l" in out
    assert "\x1b[?1049l" in out


def test_cleanup_terminal_silent_if_stream_write_fails():
    """If even the fallback stream.write blows up (closed stdout, etc.)
    cleanup_terminal must NOT raise. We're about to os._exit; if
    cleanup itself crashes we'd potentially leave the user with both
    a corrupted terminal AND an unexpected stack trace."""
    from polily.tui.terminal_cleanup import cleanup_terminal

    class BrokenStream:
        def write(self, _):
            raise OSError("stdout is closed")

        def flush(self):
            raise OSError("stdout is closed")

    # Must not raise.
    cleanup_terminal(app=None, stream=BrokenStream())
