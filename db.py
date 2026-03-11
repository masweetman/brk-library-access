import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "brk_access.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                proxy_server   TEXT    NOT NULL DEFAULT '',
                proxy_username TEXT    NOT NULL DEFAULT '',
                proxy_password TEXT    NOT NULL DEFAULT '',
                user_data_dir  TEXT    NOT NULL DEFAULT '',
                headless       INTEGER NOT NULL DEFAULT 0,
                timeout        INTEGER NOT NULL DEFAULT 15000,
                delay_min_ms   INTEGER NOT NULL DEFAULT 300,
                delay_max_ms   INTEGER NOT NULL DEFAULT 900,
                slow_mo_ms     INTEGER NOT NULL DEFAULT 100
            );
            INSERT OR IGNORE INTO settings (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS tasks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT    NOT NULL DEFAULT '',
                access_type         TEXT    NOT NULL CHECK (access_type IN ('nyt', 'wp', 'wsj')),
                library_card_number TEXT    NOT NULL DEFAULT '',
                library_last_name   TEXT    NOT NULL DEFAULT '',
                access_email        TEXT    NOT NULL DEFAULT '',
                access_password     TEXT    NOT NULL DEFAULT '',
                access_cookies      TEXT    NOT NULL DEFAULT '',
                created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
                last_run_at         TEXT,
                last_run_status     TEXT
            );

            CREATE TABLE IF NOT EXISTS task_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                status      TEXT,
                output      TEXT    NOT NULL DEFAULT ''
            );
        """)
