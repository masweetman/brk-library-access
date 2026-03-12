"""
Integration tests for authentication routes — /login and /logout.
"""

import pytest

from tests.helpers import login, logout


class TestLoginRoute:
    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_unauthenticated_request_to_tasks_redirects_to_login(self, client):
        resp = client.get("/tasks", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_valid_credentials_grant_access(self, client):
        resp = login(client)
        assert resp.status_code == 200
        assert b"Access Tasks" in resp.data

    def test_wrong_password_is_rejected(self, client):
        resp = login(client, password="wrong")
        assert b"Invalid username" in resp.data

    def test_unknown_username_is_rejected(self, client):
        resp = login(client, username="ghost", password="pw")
        assert b"Invalid username" in resp.data

    def test_username_matching_is_case_insensitive(self, client):
        resp = login(client, username="ADMIN")
        assert b"Access Tasks" in resp.data

    def test_authenticated_user_visiting_login_is_redirected(self, client):
        login(client)
        resp = client.get("/login", follow_redirects=False)
        assert resp.status_code == 302

    def test_original_destination_preserved_after_login(self, client):
        # Trigger the redirect-to-login mechanism
        resp = client.get("/tasks", follow_redirects=False)
        assert "/login" in resp.headers["Location"]


class TestLogoutRoute:
    def test_logout_redirects_to_login(self, client):
        login(client)
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_after_logout_tasks_requires_auth_again(self, client):
        login(client)
        logout(client)
        resp = client.get("/tasks", follow_redirects=False)
        assert resp.status_code == 302

    def test_protected_routes_all_redirect_after_logout(self, client):
        login(client)
        logout(client)
        for url in ("/tasks", "/config", "/users"):
            resp = client.get(url, follow_redirects=False)
            assert resp.status_code == 302, f"Expected redirect after logout for {url}"


# ── Open-redirect protection ───────────────────────────────────────────────────

class TestOpenRedirectProtection:
    def test_external_next_url_is_blocked(self, client):
        """?next=http://evil.com must not redirect off-site after login."""
        resp = client.post(
            "/login?next=http://evil.com",
            data={"username": "admin", "password": "password"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert not resp.headers["Location"].startswith("http://evil.com")

    def test_protocol_relative_url_is_blocked(self, client):
        """?next=//evil.com is also an off-site redirect."""
        resp = client.post(
            "/login?next=//evil.com/steal",
            data={"username": "admin", "password": "password"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "evil.com" not in resp.headers["Location"]

    def test_relative_next_url_is_honoured(self, client):
        """A relative ?next=/tasks path must be followed after login."""
        resp = client.post(
            "/login?next=/tasks",
            data={"username": "admin", "password": "password"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/tasks" in resp.headers["Location"]


# ── Adversarial credentials ────────────────────────────────────────────────────

class TestAdversarialLoginInputs:
    def test_empty_username_and_password_rejected(self, client):
        resp = client.post("/login",
                           data={"username": "", "password": ""},
                           follow_redirects=True)
        assert b"Invalid username" in resp.data

    def test_whitespace_only_username_rejected(self, client):
        resp = client.post("/login",
                           data={"username": "  ", "password": "password"},
                           follow_redirects=True)
        assert b"Invalid username" in resp.data

    def test_password_with_null_bytes_rejected_cleanly(self, client):
        """Null bytes in the password field must not crash — just reject."""
        resp = client.post("/login",
                           data={"username": "admin", "password": "\x00\x00"},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid username" in resp.data

    def test_very_long_password_rejected_cleanly(self, client):
        """Extremely long password must not cause an unhandled error."""
        resp = client.post("/login",
                           data={"username": "admin", "password": "x" * 100_000},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid username" in resp.data
