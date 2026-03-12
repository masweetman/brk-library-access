"""
Tests for app.py — Flask routes, auth, task CRUD, and the cookie-expiry helper.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as db_module
from app import app, _parse_cookie_expiry
from db import init_db


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Flask test client backed by a fresh in-memory-equivalent temp DB."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    init_db()
    with app.test_client() as c:
        yield c


def login(client, username="admin", password="password"):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=True)


def login_as_admin(client):
    return login(client)


# ── _parse_cookie_expiry ───────────────────────────────────────────────────────

class TestParseCookieExpiry:
    def test_returns_none_for_empty_string(self):
        assert _parse_cookie_expiry("") is None

    def test_returns_none_for_invalid_json(self):
        assert _parse_cookie_expiry("not json") is None

    def test_returns_none_for_empty_list(self):
        assert _parse_cookie_expiry("[]") is None

    def test_returns_none_when_no_expiration_date(self):
        cookies = json.dumps([{"name": "foo", "value": "bar"}])
        assert _parse_cookie_expiry(cookies) is None

    def test_parses_unix_timestamp(self):
        # 2025-01-01 00:00:00 UTC = 1735689600
        cookies = json.dumps([{"name": "foo", "value": "bar", "expirationDate": 1735689600}])
        result = _parse_cookie_expiry(cookies)
        assert result == "2025-01-01 00:00:00"

    def test_uses_first_cookie_only(self):
        # First cookie expires 2025-01-01, second expires 2030-01-01
        cookies = json.dumps([
            {"name": "a", "expirationDate": 1735689600},   # 2025-01-01
            {"name": "b", "expirationDate": 1893456000},   # 2030-01-01
        ])
        result = _parse_cookie_expiry(cookies)
        assert result == "2025-01-01 00:00:00"

    def test_accepts_float_timestamp(self):
        cookies = json.dumps([{"name": "x", "expirationDate": 1735689600.5}])
        result = _parse_cookie_expiry(cookies)
        assert result == "2025-01-01 00:00:00"

    def test_returns_none_for_non_list_json(self):
        assert _parse_cookie_expiry('{"name": "x"}') is None

    def test_returns_none_for_invalid_expiration_value(self):
        cookies = json.dumps([{"name": "x", "expirationDate": "not-a-number"}])
        assert _parse_cookie_expiry(cookies) is None


# ── Auth ───────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_unauthenticated_redirect_to_login(self, client):
        resp = client.get("/tasks", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_with_valid_credentials(self, client):
        resp = login(client)
        assert resp.status_code == 200
        assert b"Access Tasks" in resp.data

    def test_login_with_invalid_password(self, client):
        resp = login(client, password="wrong")
        assert b"Invalid username" in resp.data

    def test_login_with_unknown_user(self, client):
        resp = login(client, username="nobody", password="pw")
        assert b"Invalid username" in resp.data

    def test_logout_redirects_to_login(self, client):
        login_as_admin(client)
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_case_insensitive_username(self, client):
        resp = login(client, username="ADMIN")
        assert resp.status_code == 200
        assert b"Access Tasks" in resp.data


# ── Task CRUD ──────────────────────────────────────────────────────────────────

VALID_TASK = {
    "name": "Test Task",
    "access_type": "nyt",
    "library_card_number": "1234567890",
    "library_last_name": "Smith",
    "access_email": "test@example.com",
    "access_password": "secret",
    "access_cookies": "",
    "schedule_enabled": "",
    "schedule_interval": "1440",
}


class TestTaskCRUD:
    def test_tasks_page_loads(self, client):
        login_as_admin(client)
        resp = client.get("/tasks")
        assert resp.status_code == 200

    def test_new_task_form_loads(self, client):
        login_as_admin(client)
        resp = client.get("/tasks/new")
        assert resp.status_code == 200

    def test_create_task(self, client):
        login_as_admin(client)
        resp = client.post("/tasks/new", data=VALID_TASK, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Test Task" in resp.data

    def test_create_task_appears_in_list(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        resp = client.get("/tasks")
        assert b"Test Task" in resp.data

    def test_create_task_with_schedule(self, client):
        login_as_admin(client)
        data = {**VALID_TASK, "schedule_enabled": "on", "schedule_interval": "720"}
        resp = client.post("/tasks/new", data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b"720" in resp.data

    def test_edit_task_form_loads(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()
        resp = client.get(f"/tasks/{task_id}/edit")
        assert resp.status_code == 200
        assert b"Test Task" in resp.data

    def test_edit_task_saves_changes(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()

        updated = {**VALID_TASK, "name": "Updated Task"}
        resp = client.post(f"/tasks/{task_id}/edit", data=updated, follow_redirects=True)
        assert b"Updated Task" in resp.data

    def test_delete_task(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()

        resp = client.post(f"/tasks/{task_id}/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Test Task" not in resp.data

    def test_unknown_task_edit_returns_403(self, client):
        login_as_admin(client)
        resp = client.get("/tasks/9999/edit")
        assert resp.status_code == 403

    def test_unknown_task_delete_returns_403(self, client):
        login_as_admin(client)
        resp = client.post("/tasks/9999/delete")
        assert resp.status_code == 403

    def test_cookies_expire_at_saved_on_create(self, client):
        login_as_admin(client)
        cookies = json.dumps([{"name": "x", "expirationDate": 1735689600}])
        data = {**VALID_TASK, "access_cookies": cookies}
        client.post("/tasks/new", data=data)
        db = db_module.get_db()
        task = db.execute("SELECT cookies_expire_at FROM tasks").fetchone()
        db.close()
        assert task["cookies_expire_at"] == "2025-01-01 00:00:00"

    def test_cookies_expire_at_saved_on_edit(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()

        cookies = json.dumps([{"name": "x", "expirationDate": 1893456000}])
        updated = {**VALID_TASK, "access_cookies": cookies}
        client.post(f"/tasks/{task_id}/edit", data=updated)

        db = db_module.get_db()
        task = db.execute("SELECT cookies_expire_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        db.close()
        assert task["cookies_expire_at"] == "2030-01-01 00:00:00"


# ── Access control ─────────────────────────────────────────────────────────────

class TestAccessControl:
    def _create_regular_user(self, client, username="user1", password="pass1"):
        login_as_admin(client)
        client.post("/users/new", data={
            "username": username,
            "password": password,
            "is_admin": "",
        })
        client.get("/logout")

    def test_non_admin_cannot_access_config(self, client):
        self._create_regular_user(client)
        login(client, "user1", "pass1")
        resp = client.get("/config")
        assert resp.status_code == 403

    def test_non_admin_cannot_access_user_list(self, client):
        self._create_regular_user(client)
        login(client, "user1", "pass1")
        resp = client.get("/users")
        assert resp.status_code == 403

    def test_non_admin_cannot_edit_other_users_task(self, client):
        # Admin creates a task
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()
        client.get("/logout")

        # Regular user tries to edit it
        self._create_regular_user(client)
        login(client, "user1", "pass1")
        resp = client.get(f"/tasks/{task_id}/edit")
        assert resp.status_code == 403

    def test_non_admin_cannot_delete_other_users_task(self, client):
        login_as_admin(client)
        client.post("/tasks/new", data=VALID_TASK)
        db = db_module.get_db()
        task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        db.close()
        client.get("/logout")

        self._create_regular_user(client)
        login(client, "user1", "pass1")
        resp = client.post(f"/tasks/{task_id}/delete")
        assert resp.status_code == 403

    def test_non_admin_only_sees_own_tasks(self, client):
        # Admin creates a task
        login_as_admin(client)
        client.post("/tasks/new", data={**VALID_TASK, "name": "Admin Task"})
        client.get("/logout")

        # Regular user creates their own task
        self._create_regular_user(client)
        login(client, "user1", "pass1")
        client.post("/tasks/new", data={**VALID_TASK, "name": "User1 Task"})

        resp = client.get("/tasks")
        assert b"User1 Task" in resp.data
        assert b"Admin Task" not in resp.data

    def test_admin_sees_all_tasks(self, client):
        self._create_regular_user(client)
        login(client, "user1", "pass1")
        client.post("/tasks/new", data={**VALID_TASK, "name": "User1 Task"})
        client.get("/logout")

        login_as_admin(client)
        client.post("/tasks/new", data={**VALID_TASK, "name": "Admin Task"})

        resp = client.get("/tasks")
        assert b"User1 Task" in resp.data
        assert b"Admin Task" in resp.data

    def test_cannot_delete_own_admin_account(self, client):
        login_as_admin(client)
        db = db_module.get_db()
        admin_id = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]
        db.close()
        resp = client.post(f"/users/{admin_id}/delete")
        assert resp.status_code == 400


# ── User management ────────────────────────────────────────────────────────────

class TestUserManagement:
    def test_create_user(self, client):
        login_as_admin(client)
        resp = client.post("/users/new", data={
            "username": "newuser",
            "password": "newpass",
            "is_admin": "",
        }, follow_redirects=True)
        assert b"newuser" in resp.data

    def test_duplicate_username_rejected(self, client):
        login_as_admin(client)
        client.post("/users/new", data={"username": "dup", "password": "pw"})
        resp = client.post("/users/new", data={"username": "dup", "password": "pw"},
                           follow_redirects=True)
        assert b"already taken" in resp.data

    def test_create_user_requires_password(self, client):
        login_as_admin(client)
        resp = client.post("/users/new", data={"username": "nopass", "password": ""},
                           follow_redirects=True)
        assert b"required" in resp.data

    def test_edit_user_changes_username(self, client):
        login_as_admin(client)
        client.post("/users/new", data={"username": "oldname", "password": "pw"})
        db = db_module.get_db()
        user_id = db.execute("SELECT id FROM users WHERE username = 'oldname'").fetchone()["id"]
        db.close()

        resp = client.post(f"/users/{user_id}/edit",
                           data={"username": "newname", "password": "", "is_admin": ""},
                           follow_redirects=True)
        assert b"newname" in resp.data

    def test_edit_user_changes_password(self, client):
        login_as_admin(client)
        client.post("/users/new", data={"username": "pwuser", "password": "oldpass"})
        db = db_module.get_db()
        user_id = db.execute("SELECT id FROM users WHERE username = 'pwuser'").fetchone()["id"]
        db.close()

        client.post(f"/users/{user_id}/edit",
                    data={"username": "pwuser", "password": "newpass", "is_admin": ""})
        client.get("/logout")

        resp = login(client, "pwuser", "newpass")
        assert b"Access Tasks" in resp.data

    def test_delete_user(self, client):
        login_as_admin(client)
        client.post("/users/new", data={"username": "todelete", "password": "pw"})
        db = db_module.get_db()
        user_id = db.execute("SELECT id FROM users WHERE username = 'todelete'").fetchone()["id"]
        db.close()

        resp = client.post(f"/users/{user_id}/delete", follow_redirects=True)
        assert b"todelete" not in resp.data


# ── Configuration ──────────────────────────────────────────────────────────────

class TestConfig:
    def test_config_page_loads(self, client):
        login_as_admin(client)
        resp = client.get("/config")
        assert resp.status_code == 200

    def test_config_saves_settings(self, client):
        login_as_admin(client)
        resp = client.post("/config", data={
            "proxy_server":   "proxy.example.com:8080",
            "proxy_username": "proxyuser",
            "proxy_password": "proxypass",
            "user_data_dir":  "/tmp/browser",
            "headless":       "on",
            "timeout":        "20000",
            "delay_min_ms":   "500",
            "delay_max_ms":   "1200",
            "slow_mo_ms":     "150",
        }, follow_redirects=True)
        assert resp.status_code == 200

        db = db_module.get_db()
        s = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        db.close()
        assert s["proxy_server"] == "proxy.example.com:8080"
        assert s["headless"] == 1
        assert s["timeout"] == 20000


# ── Run status API ─────────────────────────────────────────────────────────────

class TestRunStatus:
    def test_run_status_404_for_unknown_run(self, client):
        login_as_admin(client)
        resp = client.get("/runs/9999/status")
        assert resp.status_code == 404
        assert resp.json["status"] == "not_found"

    def test_run_detail_404_renders_gracefully(self, client):
        login_as_admin(client)
        resp = client.get("/runs/9999")
        # run_output template should handle a None run
        assert resp.status_code == 200
