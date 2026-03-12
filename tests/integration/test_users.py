"""
Integration tests for user-management routes — /users, /users/new,
/users/<id>/edit, /users/<id>/delete.
"""

import pytest

import db as db_module
from db import verify_password
from tests.helpers import create_user, get_user_id, login, logout


class TestUserList:
    def test_user_list_renders_for_admin(self, client):
        login(client)
        resp = client.get("/users")
        assert resp.status_code == 200

    def test_user_list_blocked_for_non_admin(self, client):
        login(client)
        create_user(client, "regular", "pw")
        logout(client)
        login(client, "regular", "pw")
        resp = client.get("/users")
        assert resp.status_code == 403

    def test_user_list_shows_existing_users(self, client):
        login(client)
        create_user(client, "alice", "pw")
        resp = client.get("/users")
        assert b"alice" in resp.data


class TestCreateUser:
    def test_create_user_appears_in_list(self, client):
        login(client)
        create_user(client, "newstaff", "pw")
        resp = client.get("/users")
        assert b"newstaff" in resp.data

    def test_new_user_can_log_in(self, client):
        login(client)
        create_user(client, "newstaff", "staffpass")
        logout(client)
        resp = login(client, "newstaff", "staffpass")
        assert b"Access Tasks" in resp.data

    def test_duplicate_username_is_rejected(self, client):
        login(client)
        create_user(client, "duplicate", "pw")
        resp = create_user(client, "duplicate", "other")
        assert b"already taken" in resp.data

    def test_username_duplicate_check_is_case_insensitive(self, client):
        login(client)
        create_user(client, "CaseTest", "pw")
        resp = create_user(client, "casetest", "pw")
        assert b"already taken" in resp.data

    def test_missing_password_is_rejected(self, client):
        login(client)
        resp = client.post("/users/new", data={"username": "nopass", "password": ""},
                           follow_redirects=True)
        assert b"required" in resp.data

    def test_missing_username_is_rejected(self, client):
        login(client)
        resp = client.post("/users/new", data={"username": "", "password": "pw"},
                           follow_redirects=True)
        assert b"required" in resp.data

    def test_admin_flag_preserved(self, client):
        login(client)
        create_user(client, "newadmin", "pw", is_admin=True)
        db = db_module.get_db()
        user = db.execute("SELECT is_admin FROM users WHERE username='newadmin'").fetchone()
        db.close()
        assert user["is_admin"] == 1

    def test_non_admin_flag_stored(self, client):
        login(client)
        create_user(client, "regular", "pw", is_admin=False)
        db = db_module.get_db()
        user = db.execute("SELECT is_admin FROM users WHERE username='regular'").fetchone()
        db.close()
        assert user["is_admin"] == 0


class TestEditUser:
    def test_edit_changes_username(self, client):
        login(client)
        create_user(client, "oldname", "pw")
        user_id = get_user_id("oldname")
        client.post(f"/users/{user_id}/edit",
                    data={"username": "newname", "password": "", "is_admin": ""},
                    follow_redirects=True)
        resp = client.get("/users")
        assert b"newname" in resp.data

    def test_edit_with_new_password_allows_login(self, client):
        login(client)
        create_user(client, "pwchange", "oldpass")
        user_id = get_user_id("pwchange")
        client.post(f"/users/{user_id}/edit",
                    data={"username": "pwchange", "password": "newpass", "is_admin": ""})
        logout(client)
        resp = login(client, "pwchange", "newpass")
        assert b"Access Tasks" in resp.data

    def test_edit_without_password_preserves_existing_password(self, client):
        login(client)
        create_user(client, "stable", "stablepass")
        user_id = get_user_id("stable")
        client.post(f"/users/{user_id}/edit",
                    data={"username": "stable", "password": "", "is_admin": ""})
        logout(client)
        resp = login(client, "stable", "stablepass")
        assert b"Access Tasks" in resp.data

    def test_edit_conflicting_username_rejected(self, client):
        login(client)
        create_user(client, "alpha", "pw")
        create_user(client, "beta",  "pw")
        alpha_id = get_user_id("alpha")
        resp = client.post(f"/users/{alpha_id}/edit",
                           data={"username": "beta", "password": "", "is_admin": ""},
                           follow_redirects=True)
        assert b"already taken" in resp.data

    def test_non_admin_cannot_edit_users(self, client):
        login(client)
        create_user(client, "regular", "pw")
        user_id = get_user_id("regular")
        logout(client)
        login(client, "regular", "pw")
        resp = client.post(f"/users/{user_id}/edit",
                           data={"username": "hacked", "password": "", "is_admin": ""})
        assert resp.status_code == 403


class TestDeleteUser:
    def test_deleted_user_removed_from_list(self, client):
        login(client)
        create_user(client, "todelete", "pw")
        user_id = get_user_id("todelete")
        client.post(f"/users/{user_id}/delete", follow_redirects=True)
        resp = client.get("/users")
        assert b"todelete" not in resp.data

    def test_deleted_user_cannot_log_in(self, client):
        login(client)
        create_user(client, "todelete", "pw")
        user_id = get_user_id("todelete")
        client.post(f"/users/{user_id}/delete")
        logout(client)
        resp = login(client, "todelete", "pw")
        assert b"Invalid username" in resp.data

    def test_admin_cannot_delete_own_account(self, client):
        login(client)
        admin_id = get_user_id("admin")
        resp = client.post(f"/users/{admin_id}/delete")
        assert resp.status_code == 400

    def test_non_admin_cannot_delete_users(self, client):
        login(client)
        create_user(client, "regular", "pw")
        user_id = get_user_id("regular")
        logout(client)
        login(client, "regular", "pw")
        resp = client.post(f"/users/{user_id}/delete")
        assert resp.status_code == 403


# ── Validation / adversarial ────────────────────────────────────────────────────

class TestUserValidationEdgeCases:
    def test_whitespace_only_username_is_rejected(self, client):
        """Username that strips to empty string must be rejected."""
        login(client)
        resp = client.post("/users/new",
                           data={"username": "   ", "password": "pw"},
                           follow_redirects=True)
        assert b"required" in resp.data

    def test_edit_nonexistent_user_redirects_safely(self, client):
        """GET /users/9999/edit should redirect, not 500."""
        login(client)
        resp = client.get("/users/9999/edit", follow_redirects=False)
        assert resp.status_code == 302

    def test_edit_user_get_shows_existing_values(self, client):
        """GET edit form must pre-populate with the user's current username."""
        login(client)
        create_user(client, "showme", "pw")
        user_id = get_user_id("showme")
        resp = client.get(f"/users/{user_id}/edit")
        assert resp.status_code == 200
        assert b"showme" in resp.data

    def test_delete_nonexistent_user_does_not_crash(self, client):
        """Deleting a non-existent user should redirect cleanly."""
        login(client)
        resp = client.post("/users/9999/delete", follow_redirects=False)
        assert resp.status_code == 302

    def test_username_with_sql_injection_attempt_is_stored_safely(self, client):
        """SQL metacharacters in username must not corrupt the database."""
        login(client)
        injection = "' OR '1'='1"
        resp = create_user(client, injection, "pw")
        # Either accepted (stored safely) or rejected — must not 500
        assert resp.status_code == 200
        if b"required" not in resp.data and b"taken" not in resp.data:
            db = db_module.get_db()
            user = db.execute(
                "SELECT username FROM users WHERE username=? COLLATE NOCASE",
                (injection,),
            ).fetchone()
            db.close()
            assert user["username"] == injection
