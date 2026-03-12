"""
Unit tests for runner.py helpers — constants, config building, and subprocess
behaviour. The browser/network layer is replaced with unittest.mock throughout.
"""

import configparser
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runner import COOKIE_FILENAMES, SCRIPTS, _execute


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _task(access_type="nyt", cookies="[]"):
    return {
        "access_type":         access_type,
        "library_card_number": "ABC123",
        "library_last_name":   "Doe",
        "access_email":        "user@example.com",
        "access_password":     "hunter2",
        "access_cookies":      cookies,
    }


def _settings(tmp_path):
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


def _ok(stdout="done\n"):
    r = MagicMock()
    r.stdout, r.returncode, r.stderr = stdout, 0, ""
    return r


# ── Constants ──────────────────────────────────────────────────────────────────

class TestConstants:
    def test_scripts_covers_all_access_types(self):
        assert set(SCRIPTS.keys()) == {"nyt", "wp", "wsj"}

    def test_scripts_values_are_Path_objects(self):
        assert all(isinstance(v, Path) for v in SCRIPTS.values())

    def test_all_script_files_exist_on_disk(self):
        for key, path in SCRIPTS.items():
            assert path.exists(), f"Missing script for '{key}': {path}"

    def test_cookie_filenames_covers_all_access_types(self):
        assert set(COOKIE_FILENAMES.keys()) == {"nyt", "wp", "wsj"}

    def test_cookie_filenames_end_with_json(self):
        assert all(v.endswith(".json") for v in COOKIE_FILENAMES.values())

    def test_scripts_and_cookie_filenames_share_the_same_keys(self):
        assert set(SCRIPTS.keys()) == set(COOKIE_FILENAMES.keys())


# ── Config file construction ───────────────────────────────────────────────────

class TestConfigBuilding:
    def test_library_card_and_last_name_written(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["card"] = cfg.get("credentials", "library_card_number")
            captured["name"] = cfg.get("credentials", "last_name")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), _settings(tmp_path))

        assert captured["card"] == "ABC123"
        assert captured["name"] == "Doe"

    def test_washingtonpost_section_present_only_for_wp(self, tmp_path):
        """The [washingtonpost] section must appear for WP, not for NYT or WSJ."""
        presence = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            # args[1] is the script path — use it as key
            presence[Path(args[1]).stem] = cfg.has_section("washingtonpost")
            return _ok()

        for access_type in ("nyt", "wp", "wsj"):
            with patch("runner.subprocess.run", side_effect=fake_run):
                _execute(_task(access_type), _settings(tmp_path))

        assert presence["wp_access"]  is True
        assert presence["nytimes_access"] is False
        assert presence["wsj_access"] is False

    def test_wp_email_and_password_written_correctly(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["email"] = cfg.get("washingtonpost", "wp_email",    fallback=None)
            captured["pw"]    = cfg.get("washingtonpost", "wp_password", fallback=None)
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task("wp"), _settings(tmp_path))

        assert captured["email"] == "user@example.com"
        assert captured["pw"]    == "hunter2"

    def test_browser_section_written(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["has_browser"] = cfg.has_section("browser")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), _settings(tmp_path))

        assert captured["has_browser"] is True


# ── Cookie file construction ───────────────────────────────────────────────────

class TestCookieFile:
    def test_cookies_written_to_temp_file_verbatim(self, tmp_path):
        payload = [{"name": "sid", "value": "abc123"}]
        captured = {}

        def fake_run(args, **kw):
            with open(kw["env"]["BRK_COOKIES_FILE"]) as f:
                captured["data"] = json.load(f)
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(cookies=json.dumps(payload)), _settings(tmp_path))

        assert captured["data"] == payload

    def test_empty_cookies_written_as_empty_json_array(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            with open(kw["env"]["BRK_COOKIES_FILE"]) as f:
                captured["raw"] = f.read()
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(cookies=""), _settings(tmp_path))

        assert captured["raw"] == "[]"

    def test_cookie_filename_matches_COOKIE_FILENAMES_constant(self, tmp_path):
        for access_type in ("nyt", "wp", "wsj"):
            captured = {}

            def fake_run(args, captured=captured, **kw):
                captured["path"] = kw["env"]["BRK_COOKIES_FILE"]
                return _ok()

            with patch("runner.subprocess.run", side_effect=fake_run):
                _execute(_task(access_type), _settings(tmp_path))

            assert Path(captured["path"]).name == COOKIE_FILENAMES[access_type]


# ── Environment and process invocation ────────────────────────────────────────

class TestProcessInvocation:
    def test_brk_config_file_env_var_set(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            captured["env"] = kw["env"]
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), _settings(tmp_path))

        assert "BRK_CONFIG_FILE"  in captured["env"]
        assert "BRK_COOKIES_FILE" in captured["env"]

    def test_current_python_executable_used(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            captured["exe"] = args[0]
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), _settings(tmp_path))

        assert captured["exe"] == sys.executable

    def test_correct_script_invoked_for_each_access_type(self, tmp_path):
        for access_type in ("nyt", "wp", "wsj"):
            captured = {}

            def fake_run(args, captured=captured, **kw):
                captured["script"] = args[1]
                return _ok()

            with patch("runner.subprocess.run", side_effect=fake_run):
                _execute(_task(access_type), _settings(tmp_path))

            assert Path(captured["script"]) == SCRIPTS[access_type]


# ── Output assembly ────────────────────────────────────────────────────────────

class TestOutputAssembly:
    def test_stdout_included_in_output(self, tmp_path):
        r = MagicMock(stdout="all good\n", returncode=0, stderr="")
        with patch("runner.subprocess.run", return_value=r):
            output, code = _execute(_task(), _settings(tmp_path))
        assert "all good" in output
        assert code == 0

    def test_exit_code_appended_when_nonzero(self, tmp_path):
        r = MagicMock(stdout="partial", returncode=2, stderr="")
        with patch("runner.subprocess.run", return_value=r):
            output, code = _execute(_task(), _settings(tmp_path))
        assert "Exit code: 2" in output
        assert code == 2

    def test_stderr_appended_when_present(self, tmp_path):
        r = MagicMock(stdout="", returncode=1, stderr="Traceback: boom")
        with patch("runner.subprocess.run", return_value=r):
            output, _ = _execute(_task(), _settings(tmp_path))
        assert "Traceback: boom" in output

    def test_stderr_absent_when_empty(self, tmp_path):
        r = MagicMock(stdout="ok", returncode=0, stderr="")
        with patch("runner.subprocess.run", return_value=r):
            output, _ = _execute(_task(), _settings(tmp_path))
        assert "STDERR" not in output


# ── Proxy config ──────────────────────────────────────────────────────────────

class TestProxyConfig:
    def test_proxy_values_written_to_config(self, tmp_path):
        settings = {
            **_settings(tmp_path),
            "proxy_server":   "myproxy:8080",
            "proxy_username": "proxyuser",
            "proxy_password": "proxypass",
        }
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["server"]   = cfg.get("proxy", "server",   fallback="")
            captured["username"] = cfg.get("proxy", "username", fallback="")
            captured["password"] = cfg.get("proxy", "password", fallback="")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), settings)

        assert captured["server"]   == "myproxy:8080"
        assert captured["username"] == "proxyuser"
        assert captured["password"] == "proxypass"

    def test_empty_proxy_values_written_as_empty_strings(self, tmp_path):
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["server"] = cfg.get("proxy", "server", fallback="MISSING")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), _settings(tmp_path))

        assert captured["server"] == ""


# ── Browser config ────────────────────────────────────────────────────────────

class TestBrowserConfig:
    def test_headless_true_writes_string_true(self, tmp_path):
        settings = {**_settings(tmp_path), "headless": 1}
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["headless"] = cfg.get("browser", "headless", fallback="")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), settings)

        assert captured["headless"] == "true"

    def test_headless_false_writes_string_false(self, tmp_path):
        settings = {**_settings(tmp_path), "headless": 0}
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["headless"] = cfg.get("browser", "headless", fallback="")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), settings)

        assert captured["headless"] == "false"

    def test_timeout_and_delays_written_correctly(self, tmp_path):
        settings = {
            **_settings(tmp_path),
            "timeout":      30000,
            "delay_min_ms": 100,
            "delay_max_ms": 500,
            "slow_mo_ms":   50,
        }
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["timeout"]     = cfg.get("browser", "timeout",      fallback="")
            captured["delay_min"]   = cfg.get("browser", "delay_min_ms", fallback="")
            captured["delay_max"]   = cfg.get("browser", "delay_max_ms", fallback="")
            captured["slow_mo"]     = cfg.get("browser", "slow_mo_ms",   fallback="")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), settings)

        assert captured["timeout"]   == "30000"
        assert captured["delay_min"] == "100"
        assert captured["delay_max"] == "500"
        assert captured["slow_mo"]   == "50"

    def test_user_data_dir_fallback_when_settings_empty(self, tmp_path):
        settings = {**_settings(tmp_path), "user_data_dir": ""}
        captured = {}

        def fake_run(args, **kw):
            cfg = configparser.ConfigParser()
            cfg.read(kw["env"]["BRK_CONFIG_FILE"])
            captured["dir"] = cfg.get("browser", "user_data_dir", fallback="")
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(), settings)

        assert captured["dir"] != ""
        assert "bpl_browser_profile" in captured["dir"]


# ── Cookie file edge cases ────────────────────────────────────────────────────

class TestCookieFileEdgeCases:
    def test_whitespace_only_cookies_written_as_empty_array(self, tmp_path):
        """Whitespace-only cookie strings should be normalised to '[]'."""
        captured = {}

        def fake_run(args, **kw):
            with open(kw["env"]["BRK_COOKIES_FILE"]) as f:
                captured["raw"] = f.read()
            return _ok()

        with patch("runner.subprocess.run", side_effect=fake_run):
            _execute(_task(cookies="   \n  "), _settings(tmp_path))

        assert captured["raw"] == "[]"
