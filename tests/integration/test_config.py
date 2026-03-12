"""
Integration tests for the configuration route — /config.
Admin-only; verifies settings are persisted to the DB.
"""

import pytest

import db as db_module
from tests.helpers import create_user, login, logout

FULL_CONFIG = {
    "proxy_server":   "proxy.example.com:8080",
    "proxy_username": "proxyuser",
    "proxy_password": "proxypass",
    "user_data_dir":  "/tmp/browser_profile",
    "headless":       "on",
    "timeout":        "20000",
    "delay_min_ms":   "500",
    "delay_max_ms":   "1500",
    "slow_mo_ms":     "200",
}


class TestConfigRoute:
    def test_config_page_renders_for_admin(self, client):
        login(client)
        resp = client.get("/config")
        assert resp.status_code == 200
        assert b"proxy_server" in resp.data

    def test_config_page_blocked_for_non_admin(self, client):
        login(client)
        create_user(client, "staff", "pw")
        logout(client)
        login(client, "staff", "pw")
        resp = client.get("/config")
        assert resp.status_code == 403

    def test_saving_config_redirects_back(self, client):
        login(client)
        resp = client.post("/config", data=FULL_CONFIG)
        assert resp.status_code == 302

    def test_saved_settings_persisted_to_db(self, client):
        login(client)
        client.post("/config", data=FULL_CONFIG)
        db = db_module.get_db()
        s = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
        db.close()
        assert s["proxy_server"]   == "proxy.example.com:8080"
        assert s["proxy_username"] == "proxyuser"
        assert s["proxy_password"] == "proxypass"
        assert s["user_data_dir"]  == "/tmp/browser_profile"
        assert s["headless"]       == 1
        assert s["timeout"]        == 20000
        assert s["delay_min_ms"]   == 500
        assert s["delay_max_ms"]   == 1500
        assert s["slow_mo_ms"]     == 200

    def test_headless_off_stores_zero(self, client):
        login(client)
        data = {**FULL_CONFIG, "headless": ""}
        client.post("/config", data=data)
        db = db_module.get_db()
        s = db.execute("SELECT headless FROM settings WHERE id=1").fetchone()
        db.close()
        assert s["headless"] == 0

    def test_empty_proxy_fields_stored_as_empty_string(self, client):
        login(client)
        data = {**FULL_CONFIG, "proxy_server": "", "proxy_username": ""}
        client.post("/config", data=data)
        db = db_module.get_db()
        s = db.execute("SELECT proxy_server, proxy_username FROM settings WHERE id=1").fetchone()
        db.close()
        assert s["proxy_server"]   == ""
        assert s["proxy_username"] == ""

    def test_config_page_shows_saved_values(self, client):
        login(client)
        client.post("/config", data=FULL_CONFIG)
        resp = client.get("/config")
        assert b"proxy.example.com:8080" in resp.data

    def test_config_page_shows_defaults_before_any_save(self, client):
        """On a fresh database the form should show the seeded defaults."""
        login(client)
        resp = client.get("/config")
        assert b"15000" in resp.data  # default timeout

    def test_non_integer_timeout_falls_back_to_default(self, client):
        """Sending non-numeric string for timeout must not 500."""
        login(client)
        data = {**FULL_CONFIG, "timeout": "notanumber"}
        resp = client.post("/config", data=data, follow_redirects=True)
        assert resp.status_code == 200
        db = db_module.get_db()
        s = db.execute("SELECT timeout FROM settings WHERE id=1").fetchone()
        db.close()
        assert isinstance(s["timeout"], int)

    def test_negative_numeric_timeout_stored(self, client):
        """Negative integers are unlikely but must not crash the config save."""
        login(client)
        data = {**FULL_CONFIG, "timeout": "-1"}
        resp = client.post("/config", data=data, follow_redirects=True)
        assert resp.status_code == 200
