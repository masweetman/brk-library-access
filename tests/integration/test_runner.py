"""
Integration tests for runner.py's launch_task() and the run-status API.
These test the interaction between the runner and the database.
"""

import sqlite3
import subprocess
from unittest.mock import patch

import pytest

import db as db_module
from runner import launch_task
from tests.helpers import login, logout, create_user, create_task, get_first_task_id


def open_db(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class TestLaunchTask:
    def test_creates_task_run_record_with_running_status(self, initialized_db):
        conn = open_db(initialized_db)
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        task_id = conn.execute(
            """INSERT INTO tasks (user_id, access_type, library_card_number,
               library_last_name, access_email, access_password, access_cookies)
               VALUES (?, 'nyt', '123', 'Smith', 'e@x.com', 'pw', '[]')""",
            (admin_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("runner._run_task"):
            run_id = launch_task(task_id)

        conn = open_db(initialized_db)
        run = conn.execute("SELECT * FROM task_runs WHERE id=?", (run_id,)).fetchone()
        conn.close()
        assert run is not None
        assert run["status"]  == "running"
        assert run["task_id"] == task_id

    def test_launch_task_sets_task_last_run_status_to_running(self, initialized_db):
        conn = open_db(initialized_db)
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        task_id = conn.execute(
            """INSERT INTO tasks (user_id, access_type, library_card_number,
               library_last_name, access_email, access_password, access_cookies)
               VALUES (?, 'wp', '123', 'Doe', 'e@x.com', 'pw', '[]')""",
            (admin_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("runner._run_task"):
            launch_task(task_id)

        conn = open_db(initialized_db)
        task = conn.execute("SELECT last_run_status FROM tasks WHERE id=?", (task_id,)).fetchone()
        conn.close()
        assert task["last_run_status"] == "running"

    def test_launch_task_returns_integer_run_id(self, initialized_db):
        conn = open_db(initialized_db)
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        task_id = conn.execute(
            """INSERT INTO tasks (user_id, access_type, library_card_number,
               library_last_name, access_email, access_password, access_cookies)
               VALUES (?, 'wsj', '123', 'Lee', 'e@x.com', 'pw', '[]')""",
            (admin_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("runner._run_task"):
            run_id = launch_task(task_id)

        assert isinstance(run_id, int) and run_id > 0

    def test_multiple_launches_create_separate_run_records(self, initialized_db):
        conn = open_db(initialized_db)
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        task_id = conn.execute(
            """INSERT INTO tasks (user_id, access_type, library_card_number,
               library_last_name, access_email, access_password, access_cookies)
               VALUES (?, 'nyt', '123', 'Smith', 'e@x.com', 'pw', '[]')""",
            (admin_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("runner._run_task"):
            id1 = launch_task(task_id)
            id2 = launch_task(task_id)

        assert id1 != id2


class TestRunStatusAPI:
    def test_run_status_returns_404_for_unknown_run(self, client):
        login(client)
        resp = client.get("/runs/9999/status")
        assert resp.status_code == 404
        assert resp.json["status"] == "not_found"

    def test_run_detail_page_handles_unknown_run_gracefully(self, client):
        login(client)
        resp = client.get("/runs/9999")
        assert resp.status_code == 200

    def test_run_status_requires_authentication(self, client):
        resp = client.get("/runs/1/status", follow_redirects=False)
        assert resp.status_code == 302

    def test_task_run_history_page_renders(self, client):
        login(client)
        create_task(client)
        task_id = get_first_task_id()
        resp = client.get(f"/tasks/{task_id}/runs")
        assert resp.status_code == 200


# ── Run detail / status access control ───────────────────────────────────────

class TestRunAccessControl:
    def _make_admin_run(self, client):
        """Create a task and run as admin; return the run_id."""
        login(client)
        create_task(client, name="Admin Task")
        task_id = get_first_task_id()
        with patch("runner._run_task"):
            resp = client.post(f"/tasks/{task_id}/run", follow_redirects=False)
        run_id = int(resp.headers["Location"].split("/runs/")[1])
        logout(client)
        return run_id

    def test_non_admin_cannot_view_another_users_run_detail(self, client):
        run_id = self._make_admin_run(client)
        login(client)
        create_user(client, "stranger", "pass1")
        logout(client)
        login(client, "stranger", "pass1")
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 403

    def test_non_admin_cannot_poll_another_users_run_status(self, client):
        run_id = self._make_admin_run(client)
        login(client)
        create_user(client, "stranger", "pass1")
        logout(client)
        login(client, "stranger", "pass1")
        resp = client.get(f"/runs/{run_id}/status")
        assert resp.status_code == 403

    def test_owner_can_view_their_own_run_detail(self, client):
        run_id = self._make_admin_run(client)
        login(client)  # admin is the owner
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200

    def test_admin_can_view_any_run_status(self, client):
        run_id = self._make_admin_run(client)
        login(client)  # admin
        resp = client.get(f"/runs/{run_id}/status")
        assert resp.status_code == 200
        assert resp.json["status"] in ("running", "success", "failed", None)


# ── _run_task error handling ───────────────────────────────────────────────────

class TestRunTaskErrorHandling:
    def _make_task_and_run(self, db_path):
        conn = open_db(db_path)
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        task_id = conn.execute(
            "INSERT INTO tasks (user_id, access_type, library_card_number, "
            "library_last_name, access_email, access_password, access_cookies) "
            "VALUES (?, 'nyt', '123', 'Doe', 'e@x.com', 'pw', '[]')",
            (admin_id,),
        ).lastrowid
        run_id = conn.execute(
            "INSERT INTO task_runs (task_id, status, output) VALUES (?, 'running', '')",
            (task_id,),
        ).lastrowid
        conn.commit()
        conn.close()
        return task_id, run_id

    def test_subprocess_timeout_marks_run_as_failed(self, initialized_db):
        from runner import _run_task
        task_id, run_id = self._make_task_and_run(initialized_db)
        with patch("runner.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="python", timeout=180)):
            _run_task(task_id, run_id)
        conn = open_db(initialized_db)
        run = conn.execute("SELECT status, output FROM task_runs WHERE id=?",
                           (run_id,)).fetchone()
        conn.close()
        assert run["status"] == "failed"
        assert "timed out" in run["output"].lower()

    def test_unexpected_exception_marks_run_as_failed(self, initialized_db):
        from runner import _run_task
        task_id, run_id = self._make_task_and_run(initialized_db)
        with patch("runner.subprocess.run",
                   side_effect=OSError("Disk I/O error")):
            _run_task(task_id, run_id)
        conn = open_db(initialized_db)
        run = conn.execute("SELECT status, output FROM task_runs WHERE id=?",
                           (run_id,)).fetchone()
        conn.close()
        assert run["status"] == "failed"
        assert "Disk I/O error" in run["output"]
