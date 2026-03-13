import hashlib
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "brk_access.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (hashed_password, salt) using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = os.urandom(32).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
    return hashed, salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return candidate == hashed


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
                slow_mo_ms     INTEGER NOT NULL DEFAULT 100,
                timezone       TEXT    NOT NULL DEFAULT 'UTC'
            );
            INSERT OR IGNORE INTO settings (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password     TEXT    NOT NULL,
                salt         TEXT    NOT NULL,
                is_admin     INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name                TEXT    NOT NULL DEFAULT '',
                access_type         TEXT    NOT NULL CHECK (access_type IN ('nyt', 'wp', 'wsj')),
                library_card_number TEXT    NOT NULL DEFAULT '',
                library_last_name   TEXT    NOT NULL DEFAULT '',
                access_email        TEXT    NOT NULL DEFAULT '',
                access_password     TEXT    NOT NULL DEFAULT '',
                access_cookies      TEXT    NOT NULL DEFAULT '',
                schedule_enabled    INTEGER NOT NULL DEFAULT 0,
                schedule_interval   INTEGER NOT NULL DEFAULT 1440,
                next_run_at         TEXT,
                cookies_expire_at   TEXT,
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

        # ── Schema migration: add user_id column to tasks if upgrading ────────
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "user_id" not in cols:
            admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            admin_id = admin["id"] if admin else 1
            # SQLite won't add a NOT NULL + REFERENCES column to an existing table;
            # add it nullable first, then backfill existing rows.
            conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
            conn.execute("UPDATE tasks SET user_id = ? WHERE user_id IS NULL", (admin_id,))

        # ── Schema migration: add schedule columns to tasks if upgrading ──────
        if "schedule_enabled" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN schedule_enabled  INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE tasks ADD COLUMN schedule_interval INTEGER NOT NULL DEFAULT 1440")
            conn.execute("ALTER TABLE tasks ADD COLUMN next_run_at       TEXT")

        # ── Schema migration: add cookies_expire_at column ────────────────────
        if "cookies_expire_at" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN cookies_expire_at TEXT")

        # ── Schema migration: add timezone column to settings ─────────────────
        settings_cols = {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
        if "timezone" not in settings_cols:
            conn.execute("ALTER TABLE settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")

        # ── Seed default admin user if none exists ────────────────────────────
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            hashed, salt = hash_password("password")
            conn.execute(
                "INSERT INTO users (username, password, salt, is_admin) VALUES (?, ?, ?, 1)",
                ("admin", hashed, salt),
            )
