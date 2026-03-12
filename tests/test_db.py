"""
Tests for db.py — schema initialisation, migrations, and password utilities.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# Allow importing project modules without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import db as db_module
from db import hash_password, init_db, verify_password


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    return db_path


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ── Password hashing ───────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_returns_nonempty_strings(self):
        hashed, salt = hash_password("secret")
        assert hashed and salt

    def test_hash_is_hex(self):
        hashed, salt = hash_password("secret")
        int(hashed, 16)  # raises ValueError if not hex
        int(salt,   16)

    def test_different_salts_produce_different_hashes(self):
        h1, _ = hash_password("same", "aabbcc")
        h2, _ = hash_password("same", "ddeeff")
        assert h1 != h2

    def test_same_salt_produces_same_hash(self):
        h1, s1 = hash_password("secret", "fixedsalt")
        h2, s2 = hash_password("secret", "fixedsalt")
        assert h1 == h2
        assert s1 == s2

    def test_random_salt_generated_when_none_given(self):
        _, s1 = hash_password("pw")
        _, s2 = hash_password("pw")
        assert s1 != s2  # extremely unlikely to collide

    def test_verify_correct_password(self):
        hashed, salt = hash_password("correct")
        assert verify_password("correct", hashed, salt) is True

    def test_verify_wrong_password(self):
        hashed, salt = hash_password("correct")
        assert verify_password("wrong", hashed, salt) is False

    def test_verify_empty_password(self):
        hashed, salt = hash_password("")
        assert verify_password("", hashed, salt) is True
        assert verify_password("x", hashed, salt) is False


# ── Schema initialisation ──────────────────────────────────────────────────────

class TestInitDb:
    def test_tables_created(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"settings", "users", "tasks", "task_runs"}.issubset(tables)
        conn.close()

    def test_settings_row_seeded(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        assert row is not None
        conn.close()

    def test_default_admin_created(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        admin = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
        assert admin is not None
        assert admin["is_admin"] == 1
        conn.close()

    def test_default_admin_password_is_valid(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        admin = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
        assert verify_password("password", admin["password"], admin["salt"]) is True
        conn.close()

    def test_init_db_idempotent(self, tmp_db):
        init_db()
        init_db()  # second call must not raise or duplicate rows
        conn = open_db(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'").fetchone()[0]
        assert count == 1
        conn.close()

    def test_tasks_schema_has_schedule_columns(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert {"schedule_enabled", "schedule_interval", "next_run_at"}.issubset(cols)
        conn.close()

    def test_tasks_schema_has_cookies_expire_at(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert "cookies_expire_at" in cols
        conn.close()


# ── Migration: schedule columns ────────────────────────────────────────────────

class TestMigrations:
    def _create_legacy_db(self, db_path: Path):
        """Simulate a pre-schedule-columns database."""
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                proxy_server TEXT NOT NULL DEFAULT '',
                proxy_username TEXT NOT NULL DEFAULT '',
                proxy_password TEXT NOT NULL DEFAULT '',
                user_data_dir TEXT NOT NULL DEFAULT '',
                headless INTEGER NOT NULL DEFAULT 0,
                timeout INTEGER NOT NULL DEFAULT 15000,
                delay_min_ms INTEGER NOT NULL DEFAULT 300,
                delay_max_ms INTEGER NOT NULL DEFAULT 900,
                slow_mo_ms INTEGER NOT NULL DEFAULT 100
            );
            INSERT OR IGNORE INTO settings (id) VALUES (1);

            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL DEFAULT '',
                access_type TEXT NOT NULL CHECK (access_type IN ('nyt', 'wp', 'wsj')),
                library_card_number TEXT NOT NULL DEFAULT '',
                library_last_name TEXT NOT NULL DEFAULT '',
                access_email TEXT NOT NULL DEFAULT '',
                access_password TEXT NOT NULL DEFAULT '',
                access_cookies TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_run_at TEXT,
                last_run_status TEXT
            );

            CREATE TABLE task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                status TEXT,
                output TEXT NOT NULL DEFAULT ''
            );
        """)
        conn.close()

    def test_schedule_columns_added_to_legacy_db(self, tmp_db):
        self._create_legacy_db(tmp_db)
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert {"schedule_enabled", "schedule_interval", "next_run_at", "cookies_expire_at"}.issubset(cols)
        conn.close()
