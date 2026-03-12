"""
Integration tests for _scheduler_tick() — the background task launcher.
These tests call _scheduler_tick() synchronously against a real temp DB.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import call, patch

import pytest

import db as db_module
from app import _scheduler_tick


def _admin_id(db_path) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    conn.close()
    return uid


def _utc_str(delta_seconds: int) -> str:
    """Return a UTC datetime string offset from now by delta_seconds."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _insert_task(db_path, *, schedule_enabled=1, next_run_at, interval=60,
                 last_run_status=None) -> int:
    uid = _admin_id(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    task_id = conn.execute(
        """INSERT INTO tasks
           (user_id, access_type, library_card_number, library_last_name,
            access_email, access_password, access_cookies,
            schedule_enabled, schedule_interval, next_run_at, last_run_status)
           VALUES (?, 'nyt', '123', 'Doe', 'e@x.com', 'pw', '[]',
                   ?, ?, ?, ?)""",
        (uid, schedule_enabled, interval, next_run_at, last_run_status),
    ).lastrowid
    conn.commit()
    conn.close()
    return task_id


class TestSchedulerTick:
    def test_overdue_task_is_launched(self, initialized_db):
        """A task whose next_run_at is in the past must be launched."""
        task_id = _insert_task(initialized_db, next_run_at=_utc_str(-60))

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        mock_launch.assert_called_once_with(task_id)

    def test_future_task_is_not_launched(self, initialized_db):
        """A task whose next_run_at is in the future must not be launched."""
        _insert_task(initialized_db, next_run_at=_utc_str(3600))

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        mock_launch.assert_not_called()

    def test_disabled_task_is_not_launched(self, initialized_db):
        """A task with schedule_enabled=0 must not be launched, even if overdue."""
        _insert_task(initialized_db, schedule_enabled=0, next_run_at=_utc_str(-60))

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        mock_launch.assert_not_called()

    def test_task_with_null_next_run_at_is_not_launched(self, initialized_db):
        """schedule_enabled=1 with next_run_at=NULL must not be launched."""
        _insert_task(initialized_db, next_run_at=None)

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        mock_launch.assert_not_called()

    def test_currently_running_task_is_not_relaunched(self, initialized_db):
        """A task that is already running must be skipped to prevent overlap."""
        _insert_task(initialized_db, next_run_at=_utc_str(-60),
                     last_run_status="running")

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        mock_launch.assert_not_called()

    def test_next_run_at_is_advanced_after_launch(self, initialized_db):
        """next_run_at must be incremented by schedule_interval minutes."""
        task_id = _insert_task(initialized_db, next_run_at=_utc_str(-60), interval=60)

        with patch("app.launch_task"):
            _scheduler_tick()

        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        task = conn.execute(
            "SELECT next_run_at FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        conn.close()

        new_next = datetime.strptime(task["next_run_at"], "%Y-%m-%d %H:%M:%S")
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert new_next > now_naive, "next_run_at must be in the future"

    def test_next_run_at_advanced_before_launch_prevents_double_trigger(self, initialized_db):
        """The DB update must happen before launch_task() so a re-entrant tick
        cannot fire the same task twice."""
        task_id = _insert_task(initialized_db, next_run_at=_utc_str(-60), interval=60)

        call_order = []

        def note_launch(tid):
            conn = sqlite3.connect(str(initialized_db))
            conn.row_factory = sqlite3.Row
            t = conn.execute("SELECT next_run_at FROM tasks WHERE id=?", (tid,)).fetchone()
            conn.close()
            call_order.append(t["next_run_at"])

        with patch("app.launch_task", side_effect=note_launch):
            _scheduler_tick()

        # next_run_at at time-of-launch must already be in the future
        assert call_order, "launch_task should have been called"
        advanced = datetime.strptime(call_order[0], "%Y-%m-%d %H:%M:%S")
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert advanced > now_naive

    def test_multiple_due_tasks_all_launched(self, initialized_db):
        """Every overdue scheduled task must be launched in a single tick."""
        id1 = _insert_task(initialized_db, next_run_at=_utc_str(-120))
        id2 = _insert_task(initialized_db, next_run_at=_utc_str(-60))
        id3 = _insert_task(initialized_db, next_run_at=_utc_str(-1))

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        launched = {c.args[0] for c in mock_launch.call_args_list}
        assert {id1, id2, id3} == launched

    def test_mix_of_due_and_future_tasks_only_due_launched(self, initialized_db):
        """Only overdue tasks fire; future tasks must stay quiet."""
        due_id    = _insert_task(initialized_db, next_run_at=_utc_str(-60))
        _insert_task(initialized_db, next_run_at=_utc_str(3600))  # not due

        with patch("app.launch_task") as mock_launch:
            _scheduler_tick()

        launched = {c.args[0] for c in mock_launch.call_args_list}
        assert launched == {due_id}
