"""
Shared helper functions imported by test files.
Not pytest fixtures — imported explicitly where needed.
"""

import db as db_module

VALID_TASK = {
    "name":                 "Test Task",
    "access_type":          "nyt",
    "library_card_number":  "1234567890",
    "library_last_name":    "Smith",
    "access_email":         "test@example.com",
    "access_password":      "secret",
    "access_cookies":       "",
    "schedule_enabled":     "",
    "schedule_interval":    "1440",
}


def login(client, username="admin", password="password"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def logout(client):
    return client.get("/logout", follow_redirects=True)


def create_task(client, **overrides):
    data = {**VALID_TASK, **overrides}
    return client.post("/tasks/new", data=data, follow_redirects=True)


def create_user(client, username, password="testpass", is_admin=False):
    return client.post("/users/new", data={
        "username": username,
        "password": password,
        "is_admin": "on" if is_admin else "",
    }, follow_redirects=True)


def get_first_task_id():
    db = db_module.get_db()
    row = db.execute("SELECT id FROM tasks ORDER BY id").fetchone()
    db.close()
    return row["id"] if row else None


def get_user_id(username):
    db = db_module.get_db()
    row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    db.close()
    return row["id"] if row else None
