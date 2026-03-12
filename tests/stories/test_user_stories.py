"""
User story tests — end-to-end workflows written from the perspective of real
users of the system. Each test narrates a complete scenario with comments that
read like acceptance criteria.
"""

import json
from unittest.mock import patch

import pytest

import db as db_module
from tests.helpers import (
    VALID_TASK, create_task, create_user, get_first_task_id, get_user_id,
    login, logout,
)


# ── Story 1 ────────────────────────────────────────────────────────────────────

def test_story_admin_onboards_new_staff_member(client):
    """
    Story: A library administrator needs to give a new staff member access to
    the task-runner system.

    Given:  The system has only the default admin account.
    When:   The admin creates a new account for the staff member.
    Then:   The staff member can log in and create their own tasks.
    But:    The staff member cannot access admin-only areas (Users, Configuration).
    """
    # Admin logs in and creates a staff account
    login(client)
    create_user(client, username="jsmith", password="lib2026!")
    logout(client)

    # Staff member can log in
    resp = login(client, "jsmith", "lib2026!")
    assert b"Access Tasks" in resp.data, "Staff member should see task list after login"

    # Staff member can create a task
    resp = create_task(client, name="Smith NYT Access", access_type="nyt")
    assert resp.status_code == 200

    resp = client.get("/tasks")
    assert b"Smith NYT Access" in resp.data

    # Staff member is blocked from admin areas
    resp = client.get("/users")
    assert resp.status_code == 403, "Non-admin must not access user management"

    resp = client.get("/config")
    assert resp.status_code == 403, "Non-admin must not access configuration"


# ── Story 2 ────────────────────────────────────────────────────────────────────

def test_story_staff_creates_and_runs_a_task(client):
    """
    Story: A staff member wants to grant a patron access to the NY Times.

    Given:  The staff member is logged in.
    When:   They create a task with the patron's library card details.
    And:    They trigger a run.
    Then:   A run record is created immediately with status 'running'.
    And:    They are taken to the output page for that run.
    """
    login(client)

    # Create the task with patron details
    create_task(
        client,
        name="Patron NYT - March",
        access_type="nyt",
        library_card_number="29349012345678",
        library_last_name="Johnson",
        access_email="patron@example.com",
        access_password="patron_pw",
    )
    task_id = get_first_task_id()
    assert task_id is not None, "Task should have been created"

    # Trigger the run (mock the actual Playwright execution)
    with patch("runner._run_task"):
        resp = client.post(f"/tasks/{task_id}/run", follow_redirects=False)

    # Should redirect to the run-output page
    assert resp.status_code == 302
    run_url = resp.headers["Location"]
    assert "/runs/" in run_url

    # Run record exists in the database with status 'running'
    db = db_module.get_db()
    run = db.execute("SELECT * FROM task_runs WHERE task_id=?", (task_id,)).fetchone()
    db.close()
    assert run is not None
    assert run["status"] == "running"


# ── Story 3 ────────────────────────────────────────────────────────────────────

def test_story_staff_schedules_automatic_overnight_access(client):
    """
    Story: A staff member wants the NYT access task to run automatically
    every night so they don't have to remember to trigger it manually.

    Given:  The staff member creates a task.
    When:   They enable the schedule with a 1440-minute (24h) interval.
    Then:   The task's next_run_at is populated in the database.
    And:    Editing the task to disable scheduling clears next_run_at.
    """
    login(client)

    # Create task with scheduling enabled
    create_task(client, name="Nightly NYT", schedule_enabled="on", schedule_interval="1440")
    task_id = get_first_task_id()

    db = db_module.get_db()
    task = db.execute(
        "SELECT schedule_enabled, schedule_interval, next_run_at FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    db.close()

    assert task["schedule_enabled"]  == 1,    "Schedule should be enabled"
    assert task["schedule_interval"] == 1440, "Interval should be 1440 minutes"
    assert task["next_run_at"] is not None,   "next_run_at must be set when scheduled"

    # Staff member later decides to disable the schedule
    resp = client.post(f"/tasks/{task_id}/edit", data={
        **VALID_TASK,
        "name":              "Nightly NYT",
        "schedule_enabled":  "",     # unchecked
        "schedule_interval": "1440",
    })
    assert resp.status_code == 302

    db = db_module.get_db()
    task = db.execute(
        "SELECT schedule_enabled, next_run_at FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    db.close()

    assert task["schedule_enabled"] == 0,  "Schedule should now be disabled"
    assert task["next_run_at"] is None,    "next_run_at should be cleared"


# ── Story 4 ────────────────────────────────────────────────────────────────────

def test_story_staff_monitors_cookie_expiry(client):
    """
    Story: A staff member wants to know when their browser cookies expire so
    they know when to log back into the publication and export fresh ones.

    Given:  The staff member has a task with cookie JSON that contains an
            expirationDate field.
    When:   They save the task.
    Then:   The system parses the expiry and stores it in the database.
    And:    When they edit the task with new cookies, the expiry is updated.
    """
    login(client)

    # Cookies expiring 2025-06-15 00:00:00 UTC (timestamp: 1749945600)
    cookies_v1 = json.dumps([{
        "name": "sso_token", "value": "abc123",
        "domain": ".wsj.com", "expirationDate": 1749945600,
    }])
    create_task(client, access_type="wsj", access_cookies=cookies_v1)
    task_id = get_first_task_id()

    db = db_module.get_db()
    task = db.execute("SELECT cookies_expire_at FROM tasks WHERE id=?", (task_id,)).fetchone()
    db.close()

    assert task["cookies_expire_at"] is not None, "Expiry should be parsed and stored"
    assert task["cookies_expire_at"].startswith("2025-06-15"), \
        f"Expected 2025-06-15, got {task['cookies_expire_at']}"

    # Staff member refreshes their cookies — new ones expire later (2026-06-15)
    cookies_v2 = json.dumps([{
        "name": "sso_token", "value": "xyz999",
        "domain": ".wsj.com", "expirationDate": 1781481600,
    }])
    client.post(f"/tasks/{task_id}/edit", data={**VALID_TASK, "access_cookies": cookies_v2})

    db = db_module.get_db()
    task = db.execute("SELECT cookies_expire_at FROM tasks WHERE id=?", (task_id,)).fetchone()
    db.close()

    assert task["cookies_expire_at"].startswith("2026-06-15"), \
        "Expiry should update when new cookies are saved"


# ── Story 5 ────────────────────────────────────────────────────────────────────

def test_story_admin_configures_proxy_for_all_tasks(client):
    """
    Story: The admin wants all automation tasks to route through the library's
    residential proxy so they are less likely to be blocked.

    Given:  The admin is logged in.
    When:   They save proxy credentials in the Configuration page.
    Then:   The settings are stored in the database.
    And:    Those settings are passed to the script subprocess via config.ini.
    """
    import configparser
    from unittest.mock import MagicMock

    login(client)

    # Save proxy settings
    client.post("/config", data={
        "proxy_server":   "residential.proxy.lib:9000",
        "proxy_username": "libproxy",
        "proxy_password": "s3cret",
        "user_data_dir":  "/tmp/profile",
        "headless":       "on",
        "timeout":        "15000",
        "delay_min_ms":   "300",
        "delay_max_ms":   "900",
        "slow_mo_ms":     "100",
    })

    # Verify they're in the DB
    db = db_module.get_db()
    s = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
    db.close()
    assert s["proxy_server"]   == "residential.proxy.lib:9000"
    assert s["proxy_username"] == "libproxy"
    assert s["proxy_password"] == "s3cret"

    # Create a task and confirm the config.ini passed to the subprocess
    # includes the proxy section with the correct values
    create_task(client, name="Proxied Task")
    task_id = get_first_task_id()

    captured = {}

    def fake_run(args, **kw):
        cfg = configparser.ConfigParser()
        cfg.read(kw["env"]["BRK_CONFIG_FILE"])
        captured["server"]   = cfg.get("proxy", "server",   fallback="")
        captured["username"] = cfg.get("proxy", "username", fallback="")
        captured["password"] = cfg.get("proxy", "password", fallback="")
        r = MagicMock()
        r.stdout, r.returncode, r.stderr = "ok", 0, ""
        return r

    with patch("runner.subprocess.run", side_effect=fake_run):
        with patch("runner._run_task"):
            client.post(f"/tasks/{task_id}/run")
            # _run_task is backgrounded; call _execute directly via a fresh approach
            from runner import _execute
            db = db_module.get_db()
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            settings = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
            db.close()
            with patch("runner.subprocess.run", side_effect=fake_run):
                _execute(task, settings)

    assert captured["server"]   == "residential.proxy.lib:9000"
    assert captured["username"] == "libproxy"
    assert captured["password"] == "s3cret"


# ── Story 6 ────────────────────────────────────────────────────────────────────

def test_story_admin_reviews_run_history_across_staff(client):
    """
    Story: The admin wants to audit which staff members ran tasks and when,
    to understand usage and troubleshoot failures.

    Given:  Two staff members each have tasks.
    When:   Each staff member runs their task.
    Then:   The admin can view the run history for any task.
    And:    Each staff member can only view run history for their own tasks.
    """
    # Create two staff users
    login(client)
    create_user(client, "alice", "alicepass")
    create_user(client, "bob",   "bobpass")
    logout(client)

    # Alice creates and "runs" a task
    login(client, "alice", "alicepass")
    create_task(client, name="Alice WSJ Task", access_type="wsj")
    alice_task_id = get_first_task_id()

    with patch("runner._run_task"):
        client.post(f"/tasks/{alice_task_id}/run")
    logout(client)

    # Bob creates and "runs" a task
    login(client, "bob", "bobpass")
    create_task(client, name="Bob WP Task", access_type="wp")

    db = db_module.get_db()
    bob_task_id = db.execute(
        "SELECT id FROM tasks WHERE name='Bob WP Task'"
    ).fetchone()["id"]
    db.close()

    with patch("runner._run_task"):
        client.post(f"/tasks/{bob_task_id}/run")

    # Bob cannot see Alice's run history
    resp = client.get(f"/tasks/{alice_task_id}/runs")
    assert resp.status_code == 403, "Bob must not view Alice's run history"
    logout(client)

    # Admin can see run history for all tasks
    login(client)
    resp = client.get(f"/tasks/{alice_task_id}/runs")
    assert resp.status_code == 200, "Admin must be able to view Alice's run history"

    resp = client.get(f"/tasks/{bob_task_id}/runs")
    assert resp.status_code == 200, "Admin must be able to view Bob's run history"
