"""v0.10.1 — agent_feedback.log header must include trigger source +
both UTC and local timestamps."""
from __future__ import annotations

import pytest

from polily.agents.narrative_writer import _write_dev_feedback


class _Op:
    def __init__(self, action: str):
        self.action = action


class _Output:
    def __init__(self, dev_feedback: str, operations: list):
        self.dev_feedback = dev_feedback
        self.operations = operations


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    yield d


@pytest.mark.parametrize("trigger", ["manual", "scan", "scheduled", "movement"])
def test_each_trigger_value_serialized_in_header(log_dir, trigger):
    output = _Output(dev_feedback="test feedback", operations=[_Op("HOLD")])
    _write_dev_feedback("ev1", "Test event", output, trigger_source=trigger)
    log = (log_dir / "agent_feedback.log").read_text()
    assert f"trigger={trigger}" in log


def test_header_includes_both_utc_and_local_timestamps(log_dir):
    output = _Output(dev_feedback="x", operations=[_Op("HOLD")])
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "UTC:" in log
    assert "local:" in log


def test_header_local_label_is_english_not_chinese(log_dir):
    """User decision: 'local' stays English, NOT 本地."""
    output = _Output(dev_feedback="x", operations=[_Op("HOLD")])
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "local:" in log
    assert "本地:" not in log


def test_header_full_shape(log_dir):
    """Pin full header so future drift is loud."""
    output = _Output(dev_feedback="body", operations=[_Op("BUY"), _Op("HOLD")])
    _write_dev_feedback("ev_x", 'Title with "quote"', output, trigger_source="scheduled")
    log = (log_dir / "agent_feedback.log").read_text()

    assert "=== [UTC:" in log
    assert "| local:" in log
    assert "] trigger=scheduled" in log
    assert "polily=v" in log
    assert "event=ev_x" in log
    # quote in title gets escaped to single-quote per existing logic
    assert "title=\"Title with 'quote'\"" in log
    assert "ops=BUY,HOLD" in log
    assert " ===" in log
    assert "\nbody\n" in log


def test_header_handles_empty_operations(log_dir):
    output = _Output(dev_feedback="x", operations=[])
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "ops=none" in log


def test_header_local_timestamp_differs_from_utc_in_non_utc_tz(log_dir, monkeypatch):
    """Force a non-UTC runtime TZ (Asia/Shanghai = +08) and pin that the
    local timestamp actually differs from UTC by ~8h plus carries a real
    TZ marker. v0.10.1 review nit — the prior version of this test only
    regex-matched format and asserted both stamps `startswith("2")`,
    which passes vacuously on UTC-configured CI boxes.

    `time.tzset()` is POSIX-only; polily targets macOS/Linux per
    CLAUDE.md so this is fine. Skip cleanly on Windows just in case.
    """
    import os
    import re
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset() unavailable (Windows) — TZ test cannot force a runtime zone")

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    assert os.environ.get("TZ") == "Asia/Shanghai", "TZ env var did not stick"

    output = _Output(dev_feedback="x", operations=[_Op("HOLD")])
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    m = re.search(r"=== \[UTC: ([^|]+) \| local: ([^\]]+)\]", log)
    assert m is not None, f"timestamp block not found: {log!r}"
    utc_ts, local_ts = m.group(1).strip(), m.group(2).strip()
    assert utc_ts != local_ts, (
        f"under TZ=Asia/Shanghai, local should differ from UTC; "
        f"got utc={utc_ts!r} local={local_ts!r}"
    )
    # local stamp must end with a TZ name produced by strftime("%Z").
    # Linux/macOS report 'CST' for Asia/Shanghai; we just verify the
    # stamp has a trailing alphabetic TZ marker (3+ letters or +HHMM).
    assert re.search(r"\b[A-Z]{2,5}$|\+\d{4}$", local_ts), (
        f"local stamp missing TZ marker: {local_ts!r}"
    )
