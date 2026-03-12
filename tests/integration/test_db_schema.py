"""
Integration tests for db.py — schema creation, default data, and migrations.
These tests call init_db() against a real (temp) SQLite file.
"""

import sqlite3
from pathlib import Path

import pytest

import db as db_module
from db import hash_password, init_db, verify_password


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ── Fresh schema ───────────────────────────────────────────────────────────────

class TestSchemaCreation:
    def test_all_four_tables_created(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert {"settings", "users", "tasks", "task_runs"}.issubset(tables)

    def test_settings_seed_row_exists(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
        conn.close()
        assert row is not None

    def test_settings_default_values(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        s = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
        conn.close()
        assert s["headless"]     == 0
        assert s["timeout"]      == 15000
        assert s["delay_min_ms"] == 300
        assert s["delay_max_ms"] == 900
        assert s["slow_mo_ms"]   == 100

    def test_default_admin_user_created(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        admin = conn.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        conn.close()
        assert admin is not None
        assert admin["is_admin"] == 1

    def test_default_admin_password_is_password(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        admin = conn.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        conn.close()
        assert verify_password("password", admin["password"], admin["salt"]) is True

    def test_init_db_is_idempotent(self, tmp_db):
        init_db()
        init_db()  # must not raise or duplicate data
        conn = open_db(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_tasks_table_has_schedule_columns(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        conn.close()
        assert {"schedule_enabled", "schedule_interval", "next_run_at"}.issubset(cols)

    def test_tasks_table_has_cookies_expire_at_column(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        conn.close()
        assert "cookies_expire_at" in cols

    def test_schedule_enabled_defaults_to_zero(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        admin_id = conn.execute("SELECT id FROM users").fetchone()["id"]
        conn.execute(
            "INSERT INTO tasks (user_id, access_type) VALUES (?, 'nyt')", (admin_id,)
        )
        conn.commit()
        task = conn.execute("SELECT schedule_enabled, schedule_interval FROM tasks").fetchone()
        conn.close()
        assert task["schedule_enabled"]  == 0
        assert task["schedule_interval"] == 1440

    def test_task_runs_are_cascade_deleted_with_task(self, tmp_db):
        init_db()
        conn = open_db(tmp_db)
        conn.execute("PRAGMA foreign_keys = ON")
        admin_id = conn.execute("SELECT id FROM users").fetchone()["id"]
        task_id = conn.execute(
            "INSERT INTO tasks (user_id, access_type) VALUES (?, 'nyt')", (admin_id,)
        ).lastrowid
        conn.execute(
            "INSERT INTO task_runs (task_id, status, output) VALUES (?, 'success', '')",
            (task_id,),
        )
        conn.commit()
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        runs = conn.execute(
            "SELECT * FROM task_runs WHERE task_id=?", (task_id,)
        ).fetchall()
        conn.close()
        assert runs == []


# ── Schema migration ───────────────────────────────────────────────────────────

class TestMigrations:
    def _make_legacy_db(self, db_path: Path):
        """Create a pre-schedule-columns database to simulate an older install."""
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id=1),
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
                access_type TEXT NOT NULL CHECK (access_type IN ('nyt','wp','wsj')),
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

    def test_schedule_and_expiry_columns_added_to_legacy_db(self, tmp_db):
        self._make_legacy_db(tmp_db)
        init_db()
        conn = open_db(tmp_db)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        conn.close()
        assert {
            "schedule_enabled", "schedule_interval", "next_run_at", "cookies_expire_at"
        }.issubset(cols)

    def test_existing_rows_preserved_after_migration(self, tmp_db):
        self._make_legacy_db(tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        pw, salt = hash_password("testpw")
        conn.execute(
            "INSERT INTO users (username, password, salt) VALUES ('migrated', ?, ?)", (pw, salt)
        )
        conn.commit()
        user_id = conn.execute(
            "SELECT id FROM users WHERE username='migrated'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO tasks (user_id, access_type) VALUES (?, 'wsj')", (user_id,)
        )
        conn.commit()
        conn.close()

        init_db()

        conn = open_db(tmp_db)
        user = conn.execute("SELECT * FROM users WHERE username='migrated'").fetchone()
        task = conn.execute("SELECT * FROM tasks WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        assert user is not None
        assert task is not None
        assert task["access_type"] == "wsj"
