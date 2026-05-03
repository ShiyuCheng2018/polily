"""v0.11.0 — top-level --data-dir / --log-dir flags propagate to paths
module overrides BEFORE any subcommand runs.

Whis-review v2 / Vegeta-implementer note: original plan used
`runner.invoke(app, [..., "--help"])` to exercise the callback,
but Click/Typer's --help is an eager option that short-circuits
BEFORE the callback body runs. Test redesigned: split into
"flag is registered (no parse error)" + "callback sets override
when called directly". Both intents from the original plan
preserved across the 4 tests.
"""
from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from polily.cli import app, main
from polily.core import paths


def _reset_paths():
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


class _FakeCtx:
    """Minimal Typer/Click context stand-in for direct callback invocation.

    `main()` only reads `ctx.invoked_subcommand`. A full Click Context
    pulls in extra plumbing we don't need.
    """

    def __init__(self, invoked_subcommand=None):
        self.invoked_subcommand = invoked_subcommand


def test_data_dir_flag_registered(tmp_path):
    """Verify --data-dir is a registered option (parsing succeeds, no
    'no such option' error). --help short-circuits, so we can't
    assert on override side-effect here — see callback tests below.
    """
    _reset_paths()
    runner = CliRunner()
    custom = tmp_path / "cli_data"
    result = runner.invoke(app, ["--data-dir", str(custom), "--help"])
    # exit_code 0 = help shown cleanly; 2 = parse error (would be
    # "no such option: --data-dir" if the flag wasn't registered)
    assert result.exit_code == 0
    assert "--data-dir" in result.output
    _reset_paths()


def test_main_callback_sets_data_dir_override(tmp_path):
    """Direct unit test: calling main() with data_dir kwarg sets the
    override. Mocks the TUI launch so no real service is constructed.

    Patch targets are the source modules (polily.tui.app /
    polily.tui.service), NOT polily.cli — the imports inside the
    callback body are local-scope `from polily.tui.app import run_tui`,
    so the symbols never enter polily.cli's namespace.
    """
    _reset_paths()
    custom = tmp_path / "cli_data"
    ctx = _FakeCtx(invoked_subcommand=None)
    with patch("polily.tui.app.run_tui"), \
         patch("polily.tui.service.PolilyService"), \
         patch("polily.cli._regenerate_yaml_snapshot"), \
         patch("polily.cli._emit_migration_status_to_stderr"):
        main(ctx, data_dir=custom, log_dir=None)
    assert custom == paths._DATA_DIR_OVERRIDE
    _reset_paths()


def test_main_callback_sets_log_dir_override(tmp_path):
    """Same shape as above but for --log-dir."""
    _reset_paths()
    custom = tmp_path / "cli_logs"
    ctx = _FakeCtx(invoked_subcommand=None)
    with patch("polily.tui.app.run_tui"), \
         patch("polily.tui.service.PolilyService"), \
         patch("polily.cli._regenerate_yaml_snapshot"), \
         patch("polily.cli._emit_migration_status_to_stderr"):
        main(ctx, data_dir=None, log_dir=custom)
    assert custom == paths._LOG_DIR_OVERRIDE
    _reset_paths()


def test_no_flag_leaves_overrides_none():
    """Sanity: invoking without flags does not mutate override state."""
    _reset_paths()
    ctx = _FakeCtx(invoked_subcommand=None)
    with patch("polily.tui.app.run_tui"), \
         patch("polily.tui.service.PolilyService"), \
         patch("polily.cli._regenerate_yaml_snapshot"), \
         patch("polily.cli._emit_migration_status_to_stderr"):
        main(ctx, data_dir=None, log_dir=None)
    assert paths._DATA_DIR_OVERRIDE is None
    assert paths._LOG_DIR_OVERRIDE is None
    _reset_paths()
