"""
Integration tests for timezone configuration and time display.

The admin selects a time zone on the Settings (/config) page; every
datetime displayed on the site is then rendered in that zone.
"""

import json

import pytest

import db as db_module
from tests.helpers import create_task, get_first_task_id, login


# ── helpers ────────────────────────────────────────────────────────────────────

def _set_timezone(tz_name: str):
    db = db_module.get_db()
    db.execute("UPDATE settings SET timezone = ? WHERE id = 1", (tz_name,))
    db.commit()
    db.close()


def _set_task_last_run(task_id: int, last_run_at: str):
    db = db_module.get_db()
    db.execute("UPDATE tasks SET last_run_at = ? WHERE id = ?", (last_run_at, task_id))
    db.commit()
    db.close()


def _insert_task_run(task_id: int, started_at: str, finished_at: str | None = None):
    db = db_module.get_db()
    db.execute(
        "INSERT INTO task_runs (task_id, started_at, finished_at, status, output) "
        "VALUES (?, ?, ?, 'success', '')",
        (task_id, started_at, finished_at),
    )
    db.commit()
    db.close()


def _get_last_run_id() -> int:
    db = db_module.get_db()
    row = db.execute("SELECT id FROM task_runs ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    return row["id"]


# ── Config page ────────────────────────────────────────────────────────────────

class TestTimezoneConfig:
    def test_config_page_shows_timezone_field(self, client):
        """The settings form must include a 'timezone' input / select."""
        login(client)
        resp = client.get("/config")
        assert resp.status_code == 200
        assert b'name="timezone"' in resp.data

    def test_default_timezone_is_utc(self, client):
        """A freshly initialised database must default to UTC."""
        db = db_module.get_db()
        s = db.execute("SELECT timezone FROM settings WHERE id = 1").fetchone()
        db.close()
        assert s["timezone"] == "UTC"

    def test_saving_valid_timezone_persists(self, client):
        """Posting a valid IANA zone name saves it to the database."""
        login(client)
        client.post("/config", data={"timezone": "America/New_York"})
        db = db_module.get_db()
        s = db.execute("SELECT timezone FROM settings WHERE id = 1").fetchone()
        db.close()
        assert s["timezone"] == "America/New_York"

    def test_invalid_timezone_stored_as_utc(self, client):
        """An unrecognised zone name must be silently replaced with UTC."""
        login(client)
        client.post("/config", data={"timezone": "Not/AValidZone"})
        db = db_module.get_db()
        s = db.execute("SELECT timezone FROM settings WHERE id = 1").fetchone()
        db.close()
        assert s["timezone"] == "UTC"

    def test_config_page_reflects_saved_timezone(self, client):
        """After saving, the config page should show the chosen timezone as selected."""
        login(client)
        client.post("/config", data={"timezone": "Europe/London"})
        resp = client.get("/config")
        assert b"Europe/London" in resp.data

    def test_config_page_blocked_for_non_admin(self, client):
        """Non-admin users must not be able to read the timezone setting."""
        from tests.helpers import create_user, logout

        login(client)
        create_user(client, "staff", "pw")
        logout(client)
        login(client, "staff", "pw")
        resp = client.get("/config")
        assert resp.status_code == 403


# ── Time display on task list page ─────────────────────────────────────────────

class TestTimezoneDisplay:
    def test_tasks_page_converts_last_run_at(self, client):
        """
        UTC 2026-01-15 15:00:00 → America/New_York (EST = UTC−5) → 10:00:00.
        January is outside DST, so the offset is deterministic.
        """
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _set_task_last_run(task_id, "2026-01-15 15:00:00")
        _set_timezone("America/New_York")

        resp = client.get("/tasks")
        assert b"10:00:00" in resp.data

    def test_tasks_page_utc_unchanged(self, client):
        """With the UTC zone, the displayed time must equal the stored value."""
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _set_task_last_run(task_id, "2026-01-15 15:00:00")
        _set_timezone("UTC")

        resp = client.get("/tasks")
        assert b"15:00:00" in resp.data

    def test_tasks_page_converts_positive_offset(self, client):
        """
        UTC 2026-06-15 10:00:00 → Europe/Paris (CEST = UTC+2) → 12:00:00.
        June is in summer time for Paris.
        """
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _set_task_last_run(task_id, "2026-06-15 10:00:00")
        _set_timezone("Europe/Paris")

        resp = client.get("/tasks")
        assert b"12:00:00" in resp.data


# ── Time display on task-runs page ─────────────────────────────────────────────

class TestTimezoneTaskRuns:
    def test_task_runs_page_converts_started_at(self, client):
        """
        UTC 2026-01-15 20:00:00 → America/Chicago (CST = UTC−6) → 14:00:00.
        """
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _insert_task_run(task_id, "2026-01-15 20:00:00", "2026-01-15 20:05:00")
        _set_timezone("America/Chicago")

        resp = client.get(f"/tasks/{task_id}/runs")
        assert b"14:00:00" in resp.data

    def test_task_runs_page_converts_finished_at(self, client):
        """finished_at must also be converted."""
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _insert_task_run(task_id, "2026-01-15 20:00:00", "2026-01-15 20:05:00")
        _set_timezone("America/Chicago")

        resp = client.get(f"/tasks/{task_id}/runs")
        assert b"14:05:00" in resp.data


# ── Time display on run-detail page ───────────────────────────────────────────

class TestTimezoneRunDetail:
    def test_run_detail_page_converts_started_at(self, client):
        """
        UTC 2026-06-15 12:00:00 → Europe/Paris (CEST = UTC+2) → 14:00:00.
        """
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _insert_task_run(task_id, "2026-06-15 12:00:00", "2026-06-15 12:05:00")
        _set_timezone("Europe/Paris")

        run_id = _get_last_run_id()
        resp = client.get(f"/runs/{run_id}")
        assert b"14:00:00" in resp.data

    def test_run_detail_page_converts_finished_at(self, client):
        """finished_at on the run-output page must also be converted."""
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        assert task_id is not None
        _insert_task_run(task_id, "2026-06-15 12:00:00", "2026-06-15 12:05:00")
        _set_timezone("Europe/Paris")

        run_id = _get_last_run_id()
        resp = client.get(f"/runs/{run_id}")
        assert b"14:05:00" in resp.data


# ── Timezone label ─────────────────────────────────────────────────────────────

class TestTimezoneLabel:
    def test_tz_name_shown_next_to_cookie_expiry(self, client):
        """
        When a task has a cookie expiry, the configured timezone name must
        appear alongside the expiry datetime so users know which zone it is.
        """
        login(client)
        _set_timezone("America/Los_Angeles")

        # Create a task whose cookies expire far in the future.
        future_ts = 1_900_000_000  # ~2030
        cookies_json = json.dumps([
            {
                "expirationDate": future_ts,
                "name": "sess", "value": "x",
                "domain": "example.com", "path": "/",
                "secure": True, "httpOnly": False, "sameSite": "None",
            }
        ])
        create_task(client, access_cookies=cookies_json)

        resp = client.get("/tasks")
        assert b"America/Los_Angeles" in resp.data

    def test_tz_name_shown_on_task_form_cookie_expiry(self, client):
        """
        When editing a task that has cookie expiry data, the tz name should
        appear next to the expiry string in the task form.
        """
        login(client)
        _set_timezone("America/Los_Angeles")

        future_ts = 1_900_000_000
        cookies_json = json.dumps([
            {
                "expirationDate": future_ts,
                "name": "sess", "value": "x",
                "domain": "example.com", "path": "/",
                "secure": True, "httpOnly": False, "sameSite": "None",
            }
        ])
        create_task(client, access_cookies=cookies_json)

        task_id = get_first_task_id()
        resp = client.get(f"/tasks/{task_id}/edit")
        assert b"America/Los_Angeles" in resp.data
