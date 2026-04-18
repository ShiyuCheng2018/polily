"""Poll log now lives in `data/logs/poll-v<version>-<timestamp>.log`.

Per-restart rotation keeps history across daemon restarts without
clobbering the developer's ability to diff old vs new behavior.
"""

import re

from scanner.daemon.poll_job import _build_poll_log_path


def test_log_goes_to_data_logs_subdir(tmp_path):
    p = _build_poll_log_path(project_root=tmp_path)
    assert p.parent == tmp_path / "data" / "logs"


def test_log_filename_has_version_and_timestamp(tmp_path):
    """Filename pattern: poll-v<MAJOR.MINOR.PATCH>-<YYYYMMDD-HHMMSS>.log."""
    p = _build_poll_log_path(project_root=tmp_path)
    assert re.match(
        r"^poll-v\d+\.\d+\.\d+-\d{8}-\d{6}\.log$", p.name,
    ), f"unexpected filename: {p.name}"


def test_log_filename_uses_actual_package_version(tmp_path):
    from scanner import __version__
    p = _build_poll_log_path(project_root=tmp_path)
    assert f"-v{__version__}-" in p.name


def test_each_call_produces_a_fresh_timestamped_filename(tmp_path):
    """Two invocations (e.g. two daemon restarts) must not collide."""
    import time as _time
    p1 = _build_poll_log_path(project_root=tmp_path)
    # Sleep ~1.1s to ensure a different second-granularity timestamp.
    _time.sleep(1.1)
    p2 = _build_poll_log_path(project_root=tmp_path)
    assert p1 != p2


def test_data_logs_dir_created_if_missing(tmp_path):
    """Path builder must ensure the directory exists."""
    p = _build_poll_log_path(project_root=tmp_path)
    assert p.parent.is_dir()
