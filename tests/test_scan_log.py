"""Tests for scan log persistence."""

import tempfile
from pathlib import Path

from scanner.scan_log import (
    ScanStepRecord,
    create_log_entry,
    finish_log_entry,
    load_scan_logs,
    save_scan_logs,
)


class TestScanLogEntry:
    def test_create_running_entry(self):
        entry = create_log_entry()
        assert entry.status == "running"
        assert entry.started_at is not None
        assert entry.finished_at is None

    def test_finish_entry_completed(self):
        entry = create_log_entry()
        steps = [
            ScanStepRecord(name="获取市场数据", status="done", detail="100 个", elapsed=3.2),
            ScanStepRecord(name="过滤市场", status="done", detail="20 通过", elapsed=0.5),
        ]
        finish_log_entry(entry, "completed", steps,
                         total_markets=100, research_count=5,
                         watchlist_count=3, filtered_count=12)
        assert entry.status == "completed"
        assert entry.finished_at is not None
        assert entry.total_elapsed >= 0  # wall clock time, not sum of steps
        assert entry.research_count == 5

    def test_finish_entry_failed(self):
        entry = create_log_entry()
        finish_log_entry(entry, "failed", [], error="timeout")
        assert entry.status == "failed"
        assert entry.error == "timeout"


class TestScanLogPersistence:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "logs.json"
            entry = create_log_entry()
            finish_log_entry(entry, "completed",
                             [ScanStepRecord(name="test", status="done", elapsed=1.0)],
                             total_markets=50, research_count=3)

            save_scan_logs([entry], path)
            loaded = load_scan_logs(path)
            assert len(loaded) == 1
            assert loaded[0].scan_id == entry.scan_id
            assert loaded[0].research_count == 3

    def test_load_nonexistent_file(self):
        logs = load_scan_logs("/nonexistent/path.json")
        assert logs == []

    def test_load_corrupted_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "logs.json"
            path.write_text("not valid json")
            logs = load_scan_logs(path)
            assert logs == []

    def test_truncate_to_max(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "logs.json"
            entries = []
            for i in range(40):
                e = create_log_entry()
                e.scan_id = f"scan_{i:03d}"
                entries.append(e)

            save_scan_logs(entries, path, max_entries=10)
            loaded = load_scan_logs(path)
            assert len(loaded) == 10
            # Should keep the last 10
            assert loaded[0].scan_id == "scan_030"
            assert loaded[-1].scan_id == "scan_039"

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "dir" / "logs.json"
            save_scan_logs([], path)
            assert path.exists()
