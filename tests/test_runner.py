"""
Tests for runner.py — config building, cookie loading, and task execution helpers.
"""

import configparser
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as db_module
from db import init_db
from runner import COOKIE_FILENAMES, SCRIPTS, _execute, launch_task


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    init_db()
    return db_path


def open_db(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def make_task(db_path, access_type="nyt"):
    conn = open_db(db_path)
    user_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    task_id = conn.execute(
        """INSERT INTO tasks
            (user_id, name, access_type, library_card_number, library_last_name,
             access_email, access_password, access_cookies)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, "Test", access_type, "12345", "Smith", "e@example.com", "pw", "[]"),
    ).lastrowid
    conn.commit()
    conn.close()
    return task_id


def make_settings(db_path, **overrides):
    conn = open_db(db_path)
    defaults = dict(
        proxy_server="", proxy_username="", proxy_password="",
        user_data_dir=str(db_path.parent / "profile"),
        headless=0, timeout=15000, delay_min_ms=300, delay_max_ms=900, slow_mo_ms=100,
    )
    defaults.update(overrides)
    conn.execute(
        """UPDATE settings SET
            proxy_server=?, proxy_username=?, proxy_password=?,
            user_data_dir=?, headless=?, timeout=?,
            delay_min_ms=?, delay_max_ms=?, slow_mo_ms=?
           WHERE id=1""",
        tuple(defaults.values()),
    )
    conn.commit()
    conn.close()


# ── SCRIPTS / COOKIE_FILENAMES constants ──────────────────────────────────────

class TestConstants:
    def test_all_access_types_have_scripts(self):
        for key in ("nyt", "wp", "wsj"):
            assert key in SCRIPTS
            assert isinstance(SCRIPTS[key], Path)

    def test_script_files_exist(self):
        for key, path in SCRIPTS.items():
            assert path.exists(), f"Script missing: {path}"

    def test_all_access_types_have_cookie_filenames(self):
        for key in ("nyt", "wp", "wsj"):
            assert key in COOKIE_FILENAMES
            assert COOKIE_FILENAMES[key].endswith(".json")


# ── launch_task ────────────────────────────────────────────────────────────────

class TestLaunchTask:
    def test_creates_task_run_record(self, tmp_db):
        task_id = make_task(tmp_db)

        with patch("runner._run_task"):  # don't actually execute
            run_id = launch_task(task_id)

        conn = open_db(tmp_db)
        run = conn.execute("SELECT * FROM task_runs WHERE id=?", (run_id,)).fetchone()
        conn.close()
        assert run is not None
        assert run["status"] == "running"
        assert run["task_id"] == task_id

    def test_sets_task_last_run_status_to_running(self, tmp_db):
        task_id = make_task(tmp_db)

        with patch("runner._run_task"):
            launch_task(task_id)

        conn = open_db(tmp_db)
        task = conn.execute("SELECT last_run_status FROM tasks WHERE id=?", (task_id,)).fetchone()
        conn.close()
        assert task["last_run_status"] == "running"

    def test_returns_run_id(self, tmp_db):
        task_id = make_task(tmp_db)
        with patch("runner._run_task"):
            run_id = launch_task(task_id)
        assert isinstance(run_id, int)
        assert run_id > 0


# ── _execute (config / cookie file construction) ──────────────────────────────

class TestExecute:
    def _make_task_row(self, tmp_path, access_type="nyt", cookies="[]"):
        return {
            "access_type":         access_type,
            "library_card_number": "ABC123",
            "library_last_name":   "Doe",
            "access_email":        "user@example.com",
            "access_password":     "hunter2",
            "access_cookies":      cookies,
        }

    def _make_settings_row(self, tmp_path):
        return {
            "proxy_server":   "",
            "proxy_username": "",
            "proxy_password": "",
            "user_data_dir":  str(tmp_path / "profile"),
            "headless":       1,
            "timeout":        5000,
            "delay_min_ms":   0,
            "delay_max_ms":   0,
            "slow_mo_ms":     0,
        }

    def _mock_subprocess(self, stdout="ok", returncode=0):
        result = MagicMock()
        result.stdout     = stdout
        result.returncode = returncode
        result.stderr     = ""
        return result

    def test_config_ini_contains_library_credentials(self, tmp_path):
        task     = self._make_task_row(tmp_path)
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            cfg = configparser.ConfigParser()
            cfg.read(kwargs["env"]["BRK_CONFIG_FILE"])
            captured["card"]      = cfg.get("credentials", "library_card_number")
            captured["last_name"] = cfg.get("credentials", "last_name")
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert captured["card"]      == "ABC123"
        assert captured["last_name"] == "Doe"

    def test_config_ini_contains_wp_credentials_for_wp(self, tmp_path):
        task     = self._make_task_row(tmp_path, access_type="wp")
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            cfg = configparser.ConfigParser()
            cfg.read(kwargs["env"]["BRK_CONFIG_FILE"])
            captured["email"]    = cfg.get("washingtonpost", "wp_email",    fallback=None)
            captured["password"] = cfg.get("washingtonpost", "wp_password", fallback=None)
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert captured["email"]    == "user@example.com"
        assert captured["password"] == "hunter2"

    def test_config_ini_no_wp_section_for_nyt(self, tmp_path):
        task     = self._make_task_row(tmp_path, access_type="nyt")
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            cfg = configparser.ConfigParser()
            cfg.read(kwargs["env"]["BRK_CONFIG_FILE"])
            captured["has_wp"] = cfg.has_section("washingtonpost")
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert captured["has_wp"] is False

    def test_cookies_written_to_temp_file(self, tmp_path):
        cookies  = json.dumps([{"name": "sid", "value": "abc123"}])
        task     = self._make_task_row(tmp_path, cookies=cookies)
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            with open(kwargs["env"]["BRK_COOKIES_FILE"]) as f:
                captured["cookies"] = json.load(f)
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert captured["cookies"] == [{"name": "sid", "value": "abc123"}]

    def test_empty_cookies_written_as_empty_list(self, tmp_path):
        task     = self._make_task_row(tmp_path, cookies="")
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            with open(kwargs["env"]["BRK_COOKIES_FILE"]) as f:
                captured["cookies"] = f.read()
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert captured["cookies"] == "[]"

    def test_returns_stdout_on_success(self, tmp_path):
        task     = self._make_task_row(tmp_path)
        settings = self._make_settings_row(tmp_path)

        with patch("runner.subprocess.run", return_value=self._mock_subprocess(stdout="done\n")):
            output, code = _execute(task, settings)

        assert "done" in output
        assert code == 0

    def test_appends_stderr_on_failure(self, tmp_path):
        task     = self._make_task_row(tmp_path)
        settings = self._make_settings_row(tmp_path)
        result   = MagicMock(stdout="", returncode=1, stderr="boom")

        with patch("runner.subprocess.run", return_value=result):
            output, code = _execute(task, settings)

        assert "boom" in output
        assert code == 1

    def test_appends_exit_code_on_nonzero(self, tmp_path):
        task     = self._make_task_row(tmp_path)
        settings = self._make_settings_row(tmp_path)
        result   = MagicMock(stdout="partial", returncode=2, stderr="")

        with patch("runner.subprocess.run", return_value=result):
            output, code = _execute(task, settings)

        assert "Exit code: 2" in output

    def test_env_has_brk_config_file(self, tmp_path):
        task     = self._make_task_row(tmp_path)
        settings = self._make_settings_row(tmp_path)
        captured = {}

        def fake_run(args, **kwargs):
            captured["env"] = kwargs["env"]
            return self._mock_subprocess()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(task, settings)

        assert "BRK_CONFIG_FILE"  in captured["env"]
        assert "BRK_COOKIES_FILE" in captured["env"]

    def test_correct_script_used_for_each_access_type(self, tmp_path):
        settings = self._make_settings_row(tmp_path)
        for access_type in ("nyt", "wp", "wsj"):
            task     = self._make_task_row(tmp_path, access_type=access_type)
            captured = {}

            def fake_run(args, captured=captured, **kwargs):
                captured["script"] = args[1]
                return self._mock_subprocess()

            with patch("runner.subprocess.run", side_effect=fake_run):
                _execute(task, settings)

            assert Path(captured["script"]) == SCRIPTS[access_type]
