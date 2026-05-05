"""Shared test fixtures and factory functions."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.models import BookLevel, Market


@pytest.fixture(autouse=True)
def _i18n_default_zh_for_tests():
    """Test suite was written assuming zh as the default UI language.
    Production default flipped to en (so non-Chinese users get a sensible
    out-of-box experience), but rather than rewriting hundreds of legacy
    assertions ("任务记录" / "已过期" / "买入" etc.), we set the active
    language back to zh for the duration of each test.

    Tests that specifically exercise language toggling (test_i18n.py,
    test_app_language_toggle.py, test_pr*_views_i18n.py, etc.) call
    `set_language()` / `init_i18n()` explicitly and override this fixture
    for their own scope.
    """
    import contextlib

    from polily.tui import i18n
    i18n._ensure_bundled_loaded()
    with contextlib.suppress(ValueError):
        # catalogs not loaded (very early failure path) — test surfaces its own error
        i18n.set_language("zh")
    yield


@pytest.fixture(autouse=True)
def _clear_polily_claude_cli_env(monkeypatch):
    """v0.9.1: BaseAgent's cli_command default now reads POLILY_CLAUDE_CLI
    from the process env. On any dev box that has ever run
    `polily scheduler restart`, the user's shell exports that var — pytest
    inherits it — and any test asserting `args[0] == "claude"` flips to
    `args[0] == "/path/to/real/claude"` and fails.

    Autouse clear guarantees tests run against a clean slate. Tests that
    want a specific POLILY_CLAUDE_CLI value do `monkeypatch.setenv(...)`
    themselves — later setenv calls win on the same monkeypatch instance.
    """
    monkeypatch.delenv("POLILY_CLAUDE_CLI", raising=False)


@pytest.fixture(autouse=True)
def _suppress_agent_debug_log(monkeypatch):
    """Prevent tests from writing agent_debug.log to data/."""
    monkeypatch.setattr("polily.agents.base._dump_debug", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _block_real_launchd_writes(tmp_path_factory, monkeypatch):
    """v0.11.0 defense-in-depth (Whis-review v2 NI1 follow-up).

    Redirect ``Path.home()`` to a per-test tmp dir so any code that
    resolves ``~/Library/LaunchAgents/...`` (via ``paths.launchd_plist_path()``
    or otherwise) writes into a sandbox instead of the user's real
    LaunchAgents directory.

    Background: Task 6 surfaced a pre-existing latent bug where
    ``tests/test_wallet_view.py::test_reset_modal_sigterms_daemon_before_reset``
    didn't mock ``restart_daemon`` and so its production code path called
    real ``subprocess.run(["launchctl", "load", ...])`` AND rewrote the
    real plist via ``Path.write_bytes(...)``. The NI1 audit (which only
    grepped for ``monkeypatch.setattr(...PLIST_PATH, ...)``) missed this
    indirect-write vector.

    This fixture is belt-and-suspenders: it cannot prevent real
    ``subprocess.run(["launchctl", ...])`` calls (those operate on a
    label, not a path), but it CAN prevent the plist file rewrite so
    even an unmocked ``restart_daemon`` write becomes a no-op against
    a sandbox path.

    Tests that need to inspect the resolved sandbox plist path can read
    ``Path.home() / "Library" / "LaunchAgents" / ...`` after this fixture
    has redirected. Tests that genuinely need the real ``Path.home``
    (rare) can opt out via ``monkeypatch.setattr("pathlib.Path.home", ...)``.
    """
    safe_home = tmp_path_factory.mktemp("safe_home")
    monkeypatch.setattr("pathlib.Path.home", lambda: safe_home)


@pytest.fixture(autouse=True)
def _isolate_poll_log(monkeypatch):
    """Prevent tests from polluting prod data/poll.log + leaking tick state.

    `polily.daemon.poll_job` owns two module-level singletons:
      - `_poll_log` — a FileHandler-backed logger hard-coded to
        `<project_root>/data/poll.log`
      - `_poll_count` — monotonic tick counter

    Without this fixture, every integration test that exercises
    `global_poll()` or `_resolve_closed_market_if_position()` appends to
    the developer's live log and carries tick numbers across tests.
    Tests that need to assert on log content override this by calling
    `patch.object(poll_job, '_get_poll_log', return_value=...)` within
    the test body — patch.object stacks on top of monkeypatch.
    """
    from polily.daemon import poll_job
    poll_job._poll_log = None
    poll_job._poll_count = 0
    monkeypatch.setattr(poll_job, "_get_poll_log", lambda: MagicMock())
    yield
    poll_job._poll_log = None
    poll_job._poll_count = 0


@pytest.fixture
def polily_db(tmp_path, monkeypatch):
    """Provide a PolilyDB in a temp directory that auto-cleans up.

    Pre-v0.11.0 the yaml→db migration read ``os.getcwd()/config.yaml``,
    so chdir alone was sufficient isolation. v0.11.0 (Task 7) moved the
    read to ``paths.data_dir() / config.yaml`` which resolves via env.
    To keep the same isolation contract, the fixture now ALSO sets
    ``POLILY_DATA_DIR=tmp_path`` (additive — chdir kept per Whis-review
    S8 so any test that still does cwd-rel assertions on yaml continues
    to pass).

    Without the env line, the migration would pull in the dev box's
    real platformdirs ``config.yaml`` and bleed custom values (e.g.
    ``magnitude_threshold == 55`` instead of the Pydantic default 70)
    into every fixture user.
    """
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    db = PolilyDB(tmp_path / "polily.db")
    yield db
    db.close()
    paths.set_data_dir_override(None)


def make_market(**overrides) -> Market:
    """Factory for creating Market instances with sensible defaults."""
    defaults = dict(
        market_id="0xtest",
        event_id="ev_test",
        title="Will BTC be above $88,000 on March 30?",
        outcomes=["Yes", "No"],
        yes_price=0.55,
        no_price=0.47,
        best_bid_yes=0.54,
        best_ask_yes=0.56,
        spread_yes=0.02,
        volume=50000.0,
        open_interest=30000.0,
        resolution_time=datetime(2026, 3, 30, tzinfo=UTC),
        data_fetched_at=datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        book_depth_bids=[BookLevel(price=0.54, size=500), BookLevel(price=0.53, size=800)],
        book_depth_asks=[BookLevel(price=0.56, size=400), BookLevel(price=0.57, size=600)],
    )
    defaults.update(overrides)
    return Market(**defaults)


def make_cli_response(structured_output: dict) -> bytes:
    """Simulate claude CLI JSON output (v2.1+ array format without --json-schema).

    Matches format: [{"type":"system",...}, {"type":"result","result":"```json\n{...}\n```"}]
    """
    json_text = json.dumps(structured_output)
    return json.dumps([
        {"type": "system", "subtype": "init", "cwd": "/test", "session_id": "test-session"},
        {
            "type": "result",
            "subtype": "success",
            "result": f"```json\n{json_text}\n```",
            "session_id": "test-session",
        },
    ]).encode()


def make_event(**overrides) -> EventRow:
    """Factory for creating EventRow instances with sensible defaults."""
    defaults = dict(
        event_id="ev_test",
        title="Test Event",
        slug="test-event",
        description="This market will resolve to Yes if the condition is met based on official data from the relevant authority.",
        resolution_source="https://official-source.com",
        volume=200000,
        neg_risk=False,
        market_count=1,
        active=1,
        closed=0,
        updated_at="2026-04-10T00:00:00",
    )
    defaults.update(overrides)
    return EventRow(**defaults)


def setup_event_and_market(db, event_id="ev1", market_id="m1", **market_overrides):
    """Create an event + market in DB for testing."""
    upsert_event(make_event(event_id=event_id), db)
    defaults = dict(
        market_id=market_id,
        event_id=event_id,
        question="Test market question",
        updated_at="2026-04-10T00:00:00",
    )
    defaults.update(market_overrides)
    upsert_market(MarketRow(**defaults), db)


def make_cli_response_structured(structured_output: dict) -> bytes:
    """Simulate claude CLI JSON output (v2.1+ array format with --json-schema).

    When --json-schema is used, response comes in structured_output, not result.
    """
    return json.dumps([
        {"type": "system", "subtype": "init", "cwd": "/test", "session_id": "test-session"},
        {
            "type": "result",
            "subtype": "success",
            "result": "",
            "structured_output": structured_output,
            "session_id": "test-session",
        },
    ]).encode()
