"""
Integration tests for task routes — CRUD, scheduling, access control, and
cookie-expiry persistence.
"""

import json
from unittest.mock import patch

import pytest

import db as db_module
from tests.helpers import (
    VALID_TASK, create_task, create_user, get_first_task_id, login, logout
)


# ── CRUD ───────────────────────────────────────────────────────────────────────

class TestTaskCRUD:
    def test_tasks_list_renders(self, client):
        login(client)
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert b"New Task" in resp.data

    def test_new_task_form_renders(self, client):
        login(client)
        resp = client.get("/tasks/new")
        assert resp.status_code == 200
        assert b"library_card_number" in resp.data

    def test_create_task_redirects_to_list(self, client):
        login(client)
        resp = client.post("/tasks/new", data=VALID_TASK)
        assert resp.status_code == 302

    def test_created_task_appears_in_list(self, client):
        login(client)
        create_task(client, name="My NYT Task")
        resp = client.get("/tasks")
        assert b"My NYT Task" in resp.data

    def test_edit_task_form_renders_with_existing_values(self, client):
        login(client)
        create_task(client, name="Editable")
        task_id = get_first_task_id()
        resp = client.get(f"/tasks/{task_id}/edit")
        assert resp.status_code == 200
        assert b"Editable" in resp.data

    def test_edit_task_saves_updated_name(self, client):
        login(client)
        create_task(client, name="Original")
        task_id = get_first_task_id()
        client.post(f"/tasks/{task_id}/edit", data={**VALID_TASK, "name": "Renamed"})
        resp = client.get("/tasks")
        assert b"Renamed" in resp.data
        assert b"Original" not in resp.data

    def test_delete_task_removes_it_from_list(self, client):
        login(client)
        create_task(client, name="ToDelete")
        task_id = get_first_task_id()
        client.post(f"/tasks/{task_id}/delete")
        resp = client.get("/tasks")
        assert b"ToDelete" not in resp.data

    def test_edit_nonexistent_task_returns_403(self, client):
        login(client)
        resp = client.get("/tasks/9999/edit")
        assert resp.status_code == 403

    def test_delete_nonexistent_task_returns_403(self, client):
        login(client)
        resp = client.post("/tasks/9999/delete")
        assert resp.status_code == 403


# ── Scheduling ─────────────────────────────────────────────────────────────────

class TestTaskScheduling:
    def test_schedule_fields_persisted_on_create(self, client):
        login(client)
        create_task(client, schedule_enabled="on", schedule_interval="720")
        db = db_module.get_db()
        task = db.execute(
            "SELECT schedule_enabled, schedule_interval, next_run_at FROM tasks"
        ).fetchone()
        db.close()
        assert task["schedule_enabled"]  == 1
        assert task["schedule_interval"] == 720
        assert task["next_run_at"] is not None

    def test_schedule_disabled_clears_next_run_at(self, client):
        login(client)
        # Create with schedule enabled, then edit to disable
        create_task(client, schedule_enabled="on", schedule_interval="720")
        task_id = get_first_task_id()
        client.post(f"/tasks/{task_id}/edit", data={
            **VALID_TASK, "schedule_enabled": "", "schedule_interval": "720"
        })
        db = db_module.get_db()
        task = db.execute("SELECT schedule_enabled, next_run_at FROM tasks").fetchone()
        db.close()
        assert task["schedule_enabled"] == 0
        assert task["next_run_at"] is None

    def test_schedule_interval_minimum_is_one(self, client):
        login(client)
        create_task(client, schedule_enabled="on", schedule_interval="0")
        db = db_module.get_db()
        task = db.execute("SELECT schedule_interval FROM tasks").fetchone()
        db.close()
        assert task["schedule_interval"] >= 1

    def test_next_run_at_set_when_schedule_enabled(self, client):
        login(client)
        create_task(client, schedule_enabled="on", schedule_interval="1440")
        db = db_module.get_db()
        task = db.execute("SELECT next_run_at FROM tasks").fetchone()
        db.close()
        assert task["next_run_at"] is not None


# ── Cookie expiry ──────────────────────────────────────────────────────────────

class TestCookieExpiry:
    def test_cookies_expire_at_saved_on_create(self, client):
        login(client)
        # 1735689600 = 2025-01-01 00:00:00 UTC
        cookies = json.dumps([{"name": "x", "expirationDate": 1735689600}])
        create_task(client, access_cookies=cookies)
        db = db_module.get_db()
        task = db.execute("SELECT cookies_expire_at FROM tasks").fetchone()
        db.close()
        assert task["cookies_expire_at"] == "2025-01-01 00:00:00"

    def test_cookies_expire_at_updated_on_edit(self, client):
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        # 1893456000 = 2030-01-01 00:00:00 UTC
        new_cookies = json.dumps([{"name": "x", "expirationDate": 1893456000}])
        client.post(f"/tasks/{task_id}/edit", data={**VALID_TASK, "access_cookies": new_cookies})
        db = db_module.get_db()
        task = db.execute("SELECT cookies_expire_at FROM tasks WHERE id=?", (task_id,)).fetchone()
        db.close()
        assert task["cookies_expire_at"] == "2030-01-01 00:00:00"

    def test_empty_cookies_leaves_cookies_expire_at_null(self, client):
        login(client)
        create_task(client, access_cookies="")
        db = db_module.get_db()
        task = db.execute("SELECT cookies_expire_at FROM tasks").fetchone()
        db.close()
        assert task["cookies_expire_at"] is None


# ── Access control ─────────────────────────────────────────────────────────────

class TestTaskAccessControl:
    def _setup_regular_user(self, client, username="user1", password="pass1"):
        login(client)
        create_user(client, username, password)
        logout(client)
        login(client, username, password)

    def test_regular_user_cannot_edit_another_users_task(self, client):
        login(client)
        create_task(client, name="Admin Task")
        task_id = get_first_task_id()
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        resp = client.get(f"/tasks/{task_id}/edit")
        assert resp.status_code == 403

    def test_regular_user_cannot_delete_another_users_task(self, client):
        login(client)
        create_task(client, name="Admin Task")
        task_id = get_first_task_id()
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        resp = client.post(f"/tasks/{task_id}/delete")
        assert resp.status_code == 403

    def test_regular_user_only_sees_own_tasks(self, client):
        login(client)
        create_task(client, name="Admin Task")
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        create_task(client, name="User1 Task")

        resp = client.get("/tasks")
        assert b"User1 Task" in resp.data
        assert b"Admin Task" not in resp.data

    def test_admin_sees_all_users_tasks(self, client):
        login(client)
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        create_task(client, name="User1 Task")
        logout(client)

        login(client)
        create_task(client, name="Admin Task")

        resp = client.get("/tasks")
        assert b"User1 Task" in resp.data
        assert b"Admin Task" in resp.data

    def test_admin_can_edit_any_users_task(self, client):
        login(client)
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        create_task(client, name="User Task")
        task_id = get_first_task_id()
        logout(client)

        login(client)
        resp = client.get(f"/tasks/{task_id}/edit")
        assert resp.status_code == 200


# ── Run-task route ─────────────────────────────────────────────────────────────────

class TestRunTaskRoute:
    def test_run_own_task_redirects_to_run_output(self, client):
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        from unittest.mock import patch
        with patch("runner._run_task"):
            resp = client.post(f"/tasks/{task_id}/run", follow_redirects=False)
        assert resp.status_code == 302
        assert "/runs/" in resp.headers["Location"]

    def test_run_task_unauthenticated_redirects_to_login(self, client):
        resp = client.post("/tasks/1/run", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_run_nonexistent_task_returns_403(self, client):
        login(client)
        resp = client.post("/tasks/9999/run")
        assert resp.status_code == 403

    def test_regular_user_cannot_run_another_users_task(self, client):
        login(client)
        create_task(client, name="Admin Task")
        task_id = get_first_task_id()
        create_user(client, "user1", "pass1")
        logout(client)

        login(client, "user1", "pass1")
        resp = client.post(f"/tasks/{task_id}/run")
        assert resp.status_code == 403


# ── Adversarial / chaos inputs ──────────────────────────────────────────────────

class TestAdversarialInput:
    def test_non_numeric_schedule_interval_uses_default(self, client):
        """Sending a non-integer schedule_interval must not cause a 500."""
        login(client)
        resp = client.post("/tasks/new", data={
            **VALID_TASK,
            "schedule_enabled":  "on",
            "schedule_interval": "banana",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db = db_module.get_db()
        task = db.execute("SELECT schedule_interval FROM tasks").fetchone()
        db.close()
        assert isinstance(task["schedule_interval"], int)

    def test_zero_schedule_interval_clamped_to_one(self, client):
        """schedule_interval=0 must be clamped to 1 (min guard)."""
        login(client)
        create_task(client, schedule_enabled="on", schedule_interval="0")
        db = db_module.get_db()
        task = db.execute("SELECT schedule_interval FROM tasks").fetchone()
        db.close()
        assert task["schedule_interval"] == 1

    def test_very_long_task_name_stored_without_error(self, client):
        """SQLite TEXT has no length limit; must not crash."""
        login(client)
        long_name = "X" * 5000
        resp = create_task(client, name=long_name)
        assert resp.status_code == 200
        db = db_module.get_db()
        task = db.execute("SELECT name FROM tasks").fetchone()
        db.close()
        assert task["name"] == long_name

    def test_html_in_task_name_stored_verbatim(self, client):
        """HTML special chars must be stored as-is (template escaping is Jinja's job)."""
        login(client)
        xss_name = "<script>alert(1)</script>"
        create_task(client, name=xss_name)
        db = db_module.get_db()
        task = db.execute("SELECT name FROM tasks").fetchone()
        db.close()
        assert task["name"] == xss_name
