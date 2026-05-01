"""Issue B — daemon shutdown handler must write a marker to the poll log.

Background: the daemon's `handle_shutdown` SIGTERM/SIGINT handler only
called `logger.info(...)` which goes to stderr → launchd plist /dev/null
→ invisible. Post-mortem of "why did the daemon stop?" couldn't tell
SIGTERM-by-launchctl apart from a Python crash mid-poll, because the
poll log (the one file that's actually visible) never got a shutdown
marker.

This test pins the contract: handle_shutdown writes
`── shutting down (SIGTERM) ──` (or SIGINT) to the poll log BEFORE
calling scheduler.shutdown — so even if APScheduler tears down logger
handlers during shutdown, the marker is already on disk.
"""
from __future__ import annotations

import contextlib
import logging
import signal


def test_handle_shutdown_writes_sigterm_marker_to_poll_log(tmp_path, monkeypatch):
    """SIGTERM marker must land in the poll log file."""
    # Build a real file-backed logger that mirrors what _get_poll_log() returns.
    log_path = tmp_path / "poll.log"
    fake_poll = logging.getLogger(f"test.poll.{tmp_path.name}.term")
    fake_poll.propagate = False
    fake_poll.handlers.clear()
    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(logging.Formatter("%(message)s"))
    fake_poll.addHandler(handler)
    fake_poll.setLevel(logging.INFO)

    monkeypatch.setattr("polily.daemon.poll_job._get_poll_log", lambda: fake_poll)

    sentinel = {"shutdown_called": False, "exit_code": None}

    class FakeScheduler:
        def shutdown(self, wait=False):
            sentinel["shutdown_called"] = True

    def fake_exit(code):
        sentinel["exit_code"] = code
        raise SystemExit(code)

    monkeypatch.setattr("sys.exit", fake_exit)

    # Build the handler closure the same way scheduler.run_scheduler builds it.
    from polily.daemon.scheduler import _build_shutdown_handler
    handle_shutdown = _build_shutdown_handler(FakeScheduler())

    # Trigger the handler with SIGTERM
    with contextlib.suppress(SystemExit):
        handle_shutdown(signal.SIGTERM, None)

    handler.close()
    fake_poll.removeHandler(handler)

    contents = log_path.read_text()
    assert "shutting down" in contents
    assert "SIGTERM" in contents
    assert sentinel["shutdown_called"] is True
    assert sentinel["exit_code"] == 0


def test_handle_shutdown_writes_sigint_marker_to_poll_log(tmp_path, monkeypatch):
    """SIGINT (Ctrl+C) marker must land in the poll log."""
    log_path = tmp_path / "poll.log"
    fake_poll = logging.getLogger(f"test.poll.{tmp_path.name}.int")
    fake_poll.propagate = False
    fake_poll.handlers.clear()
    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(logging.Formatter("%(message)s"))
    fake_poll.addHandler(handler)
    fake_poll.setLevel(logging.INFO)

    monkeypatch.setattr("polily.daemon.poll_job._get_poll_log", lambda: fake_poll)

    class FakeScheduler:
        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr("sys.exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    from polily.daemon.scheduler import _build_shutdown_handler
    handle_shutdown = _build_shutdown_handler(FakeScheduler())

    with contextlib.suppress(SystemExit):
        handle_shutdown(signal.SIGINT, None)

    handler.close()
    fake_poll.removeHandler(handler)

    contents = log_path.read_text()
    assert "SIGINT" in contents
    assert "shutting down" in contents


def test_handle_shutdown_marker_written_before_scheduler_shutdown(tmp_path, monkeypatch):
    """Marker must hit disk BEFORE scheduler.shutdown — APScheduler may tear
    down logger handlers during shutdown, so order matters."""
    log_path = tmp_path / "poll.log"
    fake_poll = logging.getLogger(f"test.poll.{tmp_path.name}.order")
    fake_poll.propagate = False
    fake_poll.handlers.clear()
    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(logging.Formatter("%(message)s"))
    fake_poll.addHandler(handler)
    fake_poll.setLevel(logging.INFO)
    monkeypatch.setattr("polily.daemon.poll_job._get_poll_log", lambda: fake_poll)

    call_order = []

    # Override the file handler's emit to capture timing of log write.
    original_emit = handler.emit
    def emit_wrapped(record):
        call_order.append("log_emit")
        original_emit(record)
    handler.emit = emit_wrapped

    class FakeScheduler:
        def shutdown(self, wait=False):
            call_order.append("scheduler_shutdown")

    monkeypatch.setattr("sys.exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    from polily.daemon.scheduler import _build_shutdown_handler
    handle_shutdown = _build_shutdown_handler(FakeScheduler())

    with contextlib.suppress(SystemExit):
        handle_shutdown(signal.SIGTERM, None)

    handler.close()
    fake_poll.removeHandler(handler)

    assert "log_emit" in call_order
    assert "scheduler_shutdown" in call_order
    assert call_order.index("log_emit") < call_order.index("scheduler_shutdown")


def test_handle_shutdown_swallows_log_failures(monkeypatch):
    """If the poll log fails (file deleted, disk full), handler must still
    proceed to scheduler.shutdown + sys.exit — logging is best-effort."""
    def boom():
        raise RuntimeError("pretend the log is gone")

    monkeypatch.setattr("polily.daemon.poll_job._get_poll_log", boom)

    sentinel = {"shutdown": False, "exited": False}

    class FakeScheduler:
        def shutdown(self, wait=False):
            sentinel["shutdown"] = True

    def fake_exit(code):
        sentinel["exited"] = True
        raise SystemExit(code)

    monkeypatch.setattr("sys.exit", fake_exit)

    from polily.daemon.scheduler import _build_shutdown_handler
    handle_shutdown = _build_shutdown_handler(FakeScheduler())

    with contextlib.suppress(SystemExit):
        handle_shutdown(signal.SIGTERM, None)

    assert sentinel["shutdown"] is True
    assert sentinel["exited"] is True
