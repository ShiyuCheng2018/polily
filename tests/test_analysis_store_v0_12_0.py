"""analysis_store dual-format support (legacy json + v0.12.0 markdown)."""
from polily.analysis_store import AnalysisVersion, append_analysis, get_event_analyses
from polily.core.db import PolilyDB


def _seed_event(db, event_id: str = "evt1") -> None:
    """analyses.event_id has FK to events; helper to seed a minimal parent row."""
    db.conn.execute(
        "INSERT OR IGNORE INTO events (event_id, title, slug, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (event_id, f"{event_id} title", f"{event_id}-slug",
         "2026-01-01T00:00:00Z"),
    )
    db.conn.commit()


def test_save_and_load_markdown_version(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, "evt1")
    av = AnalysisVersion(
        version=1,
        created_at="2026-05-08T10:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={"yes": 0.5},
        narrative_output="---\nnext_check_at: \"2026-05-09T10:00:00+00:00\"\n---\n\n# Body content",
        narrative_format="markdown",
        structure_score=85.0,
        score_breakdown={"spread": 90},
        mispricing_signal="none",
        elapsed_seconds=12.5,
    )
    append_analysis("evt1", av, db)
    loaded = get_event_analyses("evt1", db)
    assert len(loaded) == 1
    assert loaded[0].narrative_format == "markdown"
    # markdown rows expose narrative_output as a raw string, not a dict
    assert isinstance(loaded[0].narrative_output, str)
    assert loaded[0].narrative_output.startswith("---\n")


def test_save_and_load_legacy_json_version_default_format(tmp_path):
    """When narrative_format is omitted, it defaults to 'json' (backward compat path)."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, "evt2")
    av = AnalysisVersion(
        version=1,
        created_at="2026-05-08T10:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={"yes": 0.5},
        narrative_output={"summary": "legacy"},  # dict — will be JSON-encoded on write
        # narrative_format default = "json"
    )
    append_analysis("evt2", av, db)
    loaded = get_event_analyses("evt2", db)
    assert loaded[0].narrative_format == "json"
    # json rows expose narrative_output as a dict (legacy expectation)
    assert isinstance(loaded[0].narrative_output, dict)
    assert loaded[0].narrative_output == {"summary": "legacy"}


def test_load_event_with_mixed_formats(tmp_path):
    """User upgrades v0.11.x → v0.12.0 → mix of legacy + new in same event."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, "evt3")
    legacy = AnalysisVersion(
        version=1,
        created_at="2026-04-01T00:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={},
        narrative_output={"summary": "old"},
        narrative_format="json",
    )
    new = AnalysisVersion(
        version=2,
        created_at="2026-05-08T00:00:00+00:00",
        trigger_source="manual",
        prices_snapshot={},
        narrative_output="---\nnext_check_at: \"2026-05-10T00:00:00Z\"\n---\n\n# Body",
        narrative_format="markdown",
    )
    append_analysis("evt3", legacy, db)
    append_analysis("evt3", new, db)
    loaded = get_event_analyses("evt3", db)
    formats = sorted(v.narrative_format for v in loaded)
    assert formats == ["json", "markdown"]
    # Each row's narrative_output type matches its format
    by_fmt = {v.narrative_format: v for v in loaded}
    assert isinstance(by_fmt["json"].narrative_output, dict)
    assert isinstance(by_fmt["markdown"].narrative_output, str)
