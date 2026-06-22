import sqlite3
import pytest
from polily.core.db import PolilyDB


@pytest.fixture
def seeded_db(tmp_path):
    """A valid polily.db at tmp_path/polily.db with the full schema + seeded singletons."""
    db = PolilyDB(tmp_path / "polily.db")
    yield db
    db.close()
