"""
Shared pytest fixtures available to all test subdirectories.
"""

import pytest

import db as db_module
from app import app as flask_app
from db import init_db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """
    Redirect DB_PATH to a fresh temp file without initialising the schema.
    Used by schema/migration tests that exercise init_db() themselves.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    return db_path


@pytest.fixture()
def initialized_db(tmp_path, monkeypatch):
    """
    Redirect DB_PATH to a fresh temp file and initialise the schema.
    Used by runner/DB-level tests that need a working DB but no Flask client.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    init_db()
    return db_path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Flask test client backed by a fresh initialised DB.
    Used by route-level and story tests.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    flask_app.config["TESTING"] = True
    init_db()
    with flask_app.test_client() as c:
        yield c
