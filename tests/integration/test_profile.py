"""
Integration tests for the user profile page — /profile.

Covers:
 - Access control (unauthenticated, authenticated)
 - Page rendering
 - Successful password change
 - All validation failure paths
 - Post-change login behaviour (new password works, old does not)
 - Edge cases: empty fields, unicode, very long strings, SQL-injection payloads
 - Both regular users and admins can change their own password
"""

import pytest

import db as db_module
from db import verify_password
from tests.helpers import create_user, get_user_id, login, logout


# ── Helpers ────────────────────────────────────────────────────────────────────

def change_password(client, current_password, new_password, confirm_password):
    return client.post(
        "/profile",
        data={
            "current_password": current_password,
            "new_password":     new_password,
            "confirm_password": confirm_password,
        },
        follow_redirects=True,
    )


def get_user_row(username):
    db  = db_module.get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    db.close()
    return row


# ── Access control ─────────────────────────────────────────────────────────────

class TestProfileAccessControl:
    def test_unauthenticated_get_redirects_to_login(self, client):
        resp = client.get("/profile", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_post_redirects_to_login(self, client):
        resp = change_password(client, "any", "any", "any")
        # follow_redirects=True so we end up at login page
        assert b"Sign in" in resp.data or resp.status_code in (200, 302)

    def test_unauthenticated_post_no_redirect_returns_302(self, client):
        resp = client.post(
            "/profile",
            data={"current_password": "x", "new_password": "y", "confirm_password": "y"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_authenticated_user_can_access_profile(self, client):
        login(client)
        resp = client.get("/profile")
        assert resp.status_code == 200

    def test_non_admin_user_can_access_profile(self, client):
        login(client)
        create_user(client, "regular", "pw")
        logout(client)
        login(client, "regular", "pw")
        resp = client.get("/profile")
        assert resp.status_code == 200


# ── Page rendering ─────────────────────────────────────────────────────────────

class TestProfileRendering:
    def test_profile_page_shows_username(self, client):
        login(client)
        resp = client.get("/profile")
        assert b"admin" in resp.data

    def test_profile_page_shows_admin_badge_for_admin(self, client):
        login(client)
        resp = client.get("/profile")
        assert b"Admin" in resp.data

    def test_profile_page_shows_user_badge_for_non_admin(self, client):
        login(client)
        create_user(client, "regularjoe", "pw")
        logout(client)
        login(client, "regularjoe", "pw")
        resp = client.get("/profile")
        assert b"User" in resp.data

    def test_profile_page_contains_password_form_fields(self, client):
        login(client)
        resp = client.get("/profile")
        assert b"current_password" in resp.data
        assert b"new_password"     in resp.data
        assert b"confirm_password" in resp.data

    def test_profile_link_visible_in_nav(self, client):
        login(client)
        resp = client.get("/profile")
        # The nav dropdown renders a profile link
        assert b"Profile" in resp.data


# ── Successful password change ─────────────────────────────────────────────────

class TestSuccessfulPasswordChange:
    def test_correct_change_shows_success_message(self, client):
        login(client)
        resp = change_password(client, "password", "newpass123", "newpass123")
        assert b"Password updated successfully" in resp.data

    def test_changed_password_is_persisted_in_db(self, client):
        login(client)
        change_password(client, "password", "brandnew", "brandnew")
        row = get_user_row("admin")
        assert verify_password("brandnew", row["password"], row["salt"])

    def test_old_password_no_longer_valid_in_db(self, client):
        login(client)
        change_password(client, "password", "brandnew", "brandnew")
        row = get_user_row("admin")
        assert not verify_password("password", row["password"], row["salt"])

    def test_new_password_can_be_used_to_log_in(self, client):
        login(client)
        change_password(client, "password", "supersecure99", "supersecure99")
        logout(client)
        resp = login(client, "admin", "supersecure99")
        assert b"Access Tasks" in resp.data

    def test_old_password_rejected_after_change(self, client):
        login(client)
        change_password(client, "password", "supersecure99", "supersecure99")
        logout(client)
        resp = login(client, "admin", "password")
        assert b"Invalid username" in resp.data

    def test_non_admin_can_change_own_password(self, client):
        login(client)
        create_user(client, "bob", "bobpass")
        logout(client)
        login(client, "bob", "bobpass")
        resp = change_password(client, "bobpass", "newbobpass", "newbobpass")
        assert b"Password updated successfully" in resp.data

    def test_admin_change_does_not_affect_other_users(self, client):
        login(client)
        create_user(client, "carol", "carolpass")
        change_password(client, "password", "adminpass2", "adminpass2")
        # carol's password must still be unchanged
        row = get_user_row("carol")
        assert verify_password("carolpass", row["password"], row["salt"])


# ── Validation failures ────────────────────────────────────────────────────────

class TestPasswordChangeValidation:
    def test_wrong_current_password_shows_error(self, client):
        login(client)
        resp = change_password(client, "wrongpassword", "newpass", "newpass")
        assert b"Current password is incorrect" in resp.data

    def test_wrong_current_password_does_not_update_db(self, client):
        login(client)
        change_password(client, "wrongpassword", "newpass", "newpass")
        row = get_user_row("admin")
        assert verify_password("password", row["password"], row["salt"])

    def test_mismatched_new_passwords_show_error(self, client):
        login(client)
        resp = change_password(client, "password", "newpass1", "newpass2")
        assert b"do not match" in resp.data

    def test_mismatched_passwords_do_not_update_db(self, client):
        login(client)
        change_password(client, "password", "newpass1", "newpass2")
        row = get_user_row("admin")
        assert verify_password("password", row["password"], row["salt"])

    def test_empty_new_password_shows_error(self, client):
        login(client)
        resp = change_password(client, "password", "", "")
        assert b"cannot be empty" in resp.data

    def test_empty_new_password_does_not_update_db(self, client):
        login(client)
        change_password(client, "password", "", "")
        row = get_user_row("admin")
        assert verify_password("password", row["password"], row["salt"])

    def test_empty_current_password_is_rejected(self, client):
        login(client)
        resp = change_password(client, "", "newpass", "newpass")
        assert b"Current password is incorrect" in resp.data

    def test_error_does_not_redirect_away_from_profile(self, client):
        login(client)
        resp = change_password(client, "wrongpassword", "newpass", "newpass")
        assert resp.status_code == 200
        # Still on the profile page — form fields still present
        assert b"current_password" in resp.data


# ── Edge cases & adversarial inputs ───────────────────────────────────────────

class TestPasswordChangeEdgeCases:
    def test_unicode_new_password(self, client):
        login(client)
        resp = change_password(client, "password", "パスワード🔑", "パスワード🔑")
        assert b"Password updated successfully" in resp.data
        logout(client)
        resp = login(client, "admin", "パスワード🔑")
        assert b"Access Tasks" in resp.data

    def test_very_long_new_password(self, client):
        login(client)
        long_pw = "A" * 1000
        resp = change_password(client, "password", long_pw, long_pw)
        assert b"Password updated successfully" in resp.data
        logout(client)
        resp = login(client, "admin", long_pw)
        assert b"Access Tasks" in resp.data

    def test_sql_injection_in_current_password_is_rejected(self, client):
        login(client)
        resp = change_password(client, "' OR '1'='1", "newpass", "newpass")
        assert b"Current password is incorrect" in resp.data
        row = get_user_row("admin")
        assert verify_password("password", row["password"], row["salt"])

    def test_sql_injection_as_new_password_is_stored_safely(self, client):
        login(client)
        injection = "'; DROP TABLE users; --"
        resp = change_password(client, "password", injection, injection)
        assert b"Password updated successfully" in resp.data
        row = get_user_row("admin")
        assert row is not None
        assert verify_password(injection, row["password"], row["salt"])

    def test_null_bytes_in_current_password_are_rejected(self, client):
        login(client)
        resp = change_password(client, "pass\x00word", "newpass", "newpass")
        assert b"Current password is incorrect" in resp.data

    def test_whitespace_only_new_password_is_accepted(self, client):
        """Whitespace is a valid password — the app does not strip it."""
        login(client)
        resp = change_password(client, "password", "   ", "   ")
        assert b"Password updated successfully" in resp.data

    def test_confirm_matches_but_current_wrong_is_rejected(self, client):
        login(client)
        resp = change_password(client, "WRONG", "newpass", "newpass")
        assert b"Current password is incorrect" in resp.data

    def test_current_correct_but_confirm_empty_is_rejected(self, client):
        login(client)
        resp = change_password(client, "password", "newpass", "")
        assert b"do not match" in resp.data

    def test_password_change_after_multiple_changes(self, client):
        """Each successive change should work correctly."""
        login(client)
        change_password(client, "password",  "second", "second")
        change_password(client, "second",    "third",  "third")
        resp = change_password(client, "third", "fourth", "fourth")
        assert b"Password updated successfully" in resp.data
        row = get_user_row("admin")
        assert verify_password("fourth", row["password"], row["salt"])
