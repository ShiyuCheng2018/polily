from polily.doctor.context import build_context


def test_tier_default_when_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.setattr("polily.core.paths._DATA_DIR_OVERRIDE", None, raising=False)
    monkeypatch.setattr("platformdirs.user_data_dir", lambda *a, **k: str(tmp_path / "plat"))
    ctx = build_context()
    assert ctx.data_dir_tier == "default"


def test_tier_env_when_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "dev"))
    monkeypatch.setattr("polily.core.paths._DATA_DIR_OVERRIDE", None, raising=False)
    ctx = build_context()
    assert ctx.data_dir_tier == "env"
    assert ctx.data_dir == tmp_path / "dev"


def test_ro_conn_none_when_db_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "empty"))
    ctx = build_context()
    assert ctx.ro_conn() is None


def test_ro_conn_is_read_only(seeded_db, monkeypatch):
    monkeypatch.setenv("POLILY_DATA_DIR", str(seeded_db.db_path.parent))
    ctx = build_context()
    conn = ctx.ro_conn()
    assert conn is not None
    import pytest, sqlite3
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x(a)")
