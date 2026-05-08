"""v0.12.0 — agent_feedback.log header against AgentMarkdownOutput shape.

Header now uses ``body_chars=N`` (markdown body length) in place of the
v0.11.x ``ops=A,B`` summary, since AgentMarkdownOutput no longer carries
a structured operations list.

Other v0.10.1 invariants preserved: trigger source + dual UTC and local
timestamps + 'local' label stays English.
"""
from __future__ import annotations

import pytest

from polily.agents.narrative_writer import _write_dev_feedback
from polily.agents.schemas import AgentMarkdownOutput


def _mk_output(*, dev_feedback: str, body: str = "# Body\n\nadequate length") -> AgentMarkdownOutput:
    return AgentMarkdownOutput(
        markdown_body=body,
        next_check_at="2099-01-01T00:00:00+00:00",
        next_check_reason="r",
        dev_feedback=dev_feedback,
    )


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """v0.11.0: switched from chdir-based isolation to POLILY_DATA_DIR
    env var, matching the new paths resolver. The yielded path is
    paths.log_dir(), which equals tmp_path/'data'/'logs' under the env.
    """
    from polily.core import paths
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))
    d = paths.log_dir()  # triggers mkdir
    yield d
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


@pytest.mark.parametrize("trigger", ["manual", "scan", "scheduled", "movement"])
def test_each_trigger_value_serialized_in_header(log_dir, trigger):
    output = _mk_output(dev_feedback="test feedback")
    _write_dev_feedback("ev1", "Test event", output, trigger_source=trigger)
    log = (log_dir / "agent_feedback.log").read_text()
    assert f"trigger={trigger}" in log


def test_header_includes_both_utc_and_local_timestamps(log_dir):
    output = _mk_output(dev_feedback="x")
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "UTC:" in log
    assert "local:" in log


def test_header_local_label_is_english_not_chinese(log_dir):
    """User decision: 'local' stays English, NOT 本地."""
    output = _mk_output(dev_feedback="x")
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "local:" in log
    assert "本地:" not in log


def test_header_full_shape(log_dir):
    """Pin full header so future drift is loud.

    v0.12.0: ops= replaced by body_chars=. body length below is
    deterministic so the assertion can pin the exact integer.
    """
    body = "# Heading\n\nA body of known length."
    output = _mk_output(dev_feedback="body", body=body)
    _write_dev_feedback("ev_x", 'Title with "quote"', output, trigger_source="scheduled")
    log = (log_dir / "agent_feedback.log").read_text()

    assert "=== [UTC:" in log
    assert "| local:" in log
    assert "] trigger=scheduled" in log
    assert "polily=v" in log
    assert "event=ev_x" in log
    # quote in title gets escaped to single-quote per existing logic
    assert "title=\"Title with 'quote'\"" in log
    assert f"body_chars={len(body)}" in log
    assert " ===" in log
    assert "\nbody\n" in log


def test_header_handles_zero_length_body(log_dir):
    """Defensive: empty markdown_body still logs with body_chars=0
    (no longer 'ops=none' path; AgentMarkdownOutput's pydantic validator
    enforces a minimum body length, but that's a semantic_errors() concern,
    not a _write_dev_feedback concern)."""
    # Bypass model_validate's empty check by patching attr directly
    output = _mk_output(dev_feedback="x", body="x")
    object.__setattr__(output, "markdown_body", "")
    _write_dev_feedback("ev1", "t", output, trigger_source="manual")
    log = (log_dir / "agent_feedback.log").read_text()
    assert "body_chars=0" in log


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

    output = _mk_output(dev_feedback="x")
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
