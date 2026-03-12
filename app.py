import json
import os
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)

from db import get_db, hash_password, init_db, verify_password
from runner import launch_task

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


@app.context_processor
def inject_now_utc():
    return {"now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}


def _parse_cookie_expiry(cookies_raw: str) -> str | None:
    """Return the first cookie's expirationDate as 'YYYY-MM-DD HH:MM:SS' UTC, or None."""
    try:
        cookies = json.loads(cookies_raw)
        if not isinstance(cookies, list) or not cookies:
            return None
        exp = cookies[0].get("expirationDate")
        if exp is None or isinstance(exp, bool):
            return None
        dt = datetime.fromtimestamp(float(exp), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

# ── User model ─────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, row):
        self.id       = row["id"]
        self.username = row["username"]
        self.is_admin = bool(row["is_admin"])

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    db  = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return User(row) if row else None


# ── Helpers ────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def own_task_or_admin(task):
    return current_user.is_admin or task["user_id"] == current_user.id


def _safe_int(value, default: int) -> int:
    """Convert value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_url(next_url: str | None) -> str:
    """Return next_url only when it is a safe same-origin path; otherwise /tasks."""
    if not next_url:
        return url_for("tasks")
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return url_for("tasks")
    return next_url


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tasks"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db  = get_db()
        row = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        db.close()
        if row and verify_password(password, row["password"], row["salt"]):
            login_user(User(row))
            return redirect(_safe_url(request.args.get("next")))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── User management (admin only) ───────────────────────────────────────────────

@app.route("/users")
@login_required
@admin_required
def user_list():
    db    = get_db()
    users = db.execute("SELECT * FROM users ORDER BY username").fetchall()
    db.close()
    return render_template("users.html", users=users)


@app.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def user_new():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        is_admin = 1 if request.form.get("is_admin") else 0
        if not username or not password:
            error = "Username and password are required."
        else:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if existing:
                error = f"Username '{username}' is already taken."
                db.close()
            else:
                hashed, salt = hash_password(password)
                db.execute(
                    "INSERT INTO users (username, password, salt, is_admin) VALUES (?, ?, ?, ?)",
                    (username, hashed, salt, is_admin),
                )
                db.commit()
                db.close()
                return redirect(url_for("user_list"))
    return render_template("user_form.html", user=None, error=error)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(user_id):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return redirect(url_for("user_list"))

    error = None
    if request.method == "POST":
        username     = request.form.get("username", "").strip()
        is_admin     = 1 if request.form.get("is_admin") else 0
        new_password = request.form.get("password", "").strip()
        if not username:
            error = "Username is required."
        else:
            conflict = db.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE AND id != ?",
                (username, user_id),
            ).fetchone()
            if conflict:
                error = f"Username '{username}' is already taken."
            else:
                if new_password:
                    hashed, salt = hash_password(new_password)
                    db.execute(
                        "UPDATE users SET username = ?, password = ?, salt = ?, is_admin = ? WHERE id = ?",
                        (username, hashed, salt, is_admin, user_id),
                    )
                else:
                    db.execute(
                        "UPDATE users SET username = ?, is_admin = ? WHERE id = ?",
                        (username, is_admin, user_id),
                    )
                db.commit()
                db.close()
                return redirect(url_for("user_list"))

    db.close()
    return render_template("user_form.html", user=user, error=error)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def user_delete(user_id):
    if user_id == current_user.id:
        abort(400)
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    return redirect(url_for("user_list"))


# ── Configuration page (admin only) ───────────────────────────────────────────

@app.route("/config", methods=["GET", "POST"])
@login_required
@admin_required
def config():
    db = get_db()
    if request.method == "POST":
        db.execute(
            """UPDATE settings SET
                proxy_server   = ?,
                proxy_username = ?,
                proxy_password = ?,
                user_data_dir  = ?,
                headless       = ?,
                timeout        = ?,
                delay_min_ms   = ?,
                delay_max_ms   = ?,
                slow_mo_ms     = ?
               WHERE id = 1""",
            (
                request.form.get("proxy_server",   "").strip(),
                request.form.get("proxy_username", "").strip(),
                request.form.get("proxy_password", "").strip(),
                request.form.get("user_data_dir",  "").strip(),
                1 if request.form.get("headless") else 0,
                _safe_int(request.form.get("timeout",      ""), 15000),
                _safe_int(request.form.get("delay_min_ms", ""),   300),
                _safe_int(request.form.get("delay_max_ms", ""),   900),
                _safe_int(request.form.get("slow_mo_ms",   ""),   100),
            ),
        )
        db.commit()
        db.close()
        return redirect(url_for("config"))

    settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    db.close()
    return render_template("config.html", settings=settings)


# ── Tasks list ─────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/tasks")
@login_required
def tasks():
    db = get_db()
    if current_user.is_admin:
        rows = db.execute(
            "SELECT t.*, u.username FROM tasks t JOIN users u ON u.id = t.user_id ORDER BY t.created_at DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT t.*, u.username FROM tasks t JOIN users u ON u.id = t.user_id "
            "WHERE t.user_id = ? ORDER BY t.created_at DESC",
            (current_user.id,),
        ).fetchall()
    db.close()
    return render_template("tasks.html", tasks=rows)


# ── New task ───────────────────────────────────────────────────────────────────

@app.route("/tasks/new", methods=["GET", "POST"])
@login_required
def task_new():
    if request.method == "POST":
        db = get_db()
        sched_enabled  = 1 if request.form.get("schedule_enabled") else 0
        sched_interval = max(1, _safe_int(request.form.get("schedule_interval") or 1440, 1440))
        next_run       = f"datetime('now', '+{sched_interval} minutes')" if sched_enabled else "NULL"
        cookies_raw    = request.form.get("access_cookies", "").strip()
        cookie_expiry  = _parse_cookie_expiry(cookies_raw)
        db.execute(
            f"""INSERT INTO tasks
                (user_id, name, access_type, library_card_number, library_last_name,
                 access_email, access_password, access_cookies,
                 schedule_enabled, schedule_interval, next_run_at, cookies_expire_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {next_run}, ?)""",
            (
                current_user.id,
                request.form.get("name", "").strip(),
                request.form["access_type"],
                request.form.get("library_card_number", "").strip(),
                request.form.get("library_last_name",   "").strip(),
                request.form.get("access_email",        "").strip(),
                request.form.get("access_password",     ""),
                cookies_raw,
                sched_enabled,
                sched_interval,
                cookie_expiry,
            ),
        )
        db.commit()
        db.close()
        return redirect(url_for("tasks"))
    return render_template("task_form.html", task=None)


# ── Edit task ──────────────────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def task_edit(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or not own_task_or_admin(task):
        db.close()
        abort(403)

    if request.method == "POST":
        sched_enabled  = 1 if request.form.get("schedule_enabled") else 0
        sched_interval = max(1, _safe_int(request.form.get("schedule_interval") or 1440, 1440))
        next_run       = f"datetime('now', '+{sched_interval} minutes')" if sched_enabled else "NULL"
        cookies_raw    = request.form.get("access_cookies", "").strip()
        cookie_expiry  = _parse_cookie_expiry(cookies_raw)
        db.execute(
            f"""UPDATE tasks SET
                name                = ?,
                access_type         = ?,
                library_card_number = ?,
                library_last_name   = ?,
                access_email        = ?,
                access_password     = ?,
                access_cookies      = ?,
                schedule_enabled    = ?,
                schedule_interval   = ?,
                next_run_at         = {next_run},
                cookies_expire_at   = ?
               WHERE id = ?""",
            (
                request.form.get("name", "").strip(),
                request.form["access_type"],
                request.form.get("library_card_number", "").strip(),
                request.form.get("library_last_name",   "").strip(),
                request.form.get("access_email",        "").strip(),
                request.form.get("access_password",     ""),
                cookies_raw,
                sched_enabled,
                sched_interval,
                cookie_expiry,
                task_id,
            ),
        )
        db.commit()
        db.close()
        return redirect(url_for("tasks"))

    db.close()
    return render_template("task_form.html", task=task)


# ── Delete task ────────────────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def task_delete(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or not own_task_or_admin(task):
        db.close()
        abort(403)
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    db.close()
    return redirect(url_for("tasks"))


# ── Run task ───────────────────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/run", methods=["POST"])
@login_required
def task_run(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or not own_task_or_admin(task):
        db.close()
        abort(403)
    db.close()
    run_id = launch_task(task_id)
    return redirect(url_for("run_detail", run_id=run_id))


# ── Run history for a task ─────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/runs")
@login_required
def task_runs(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or not own_task_or_admin(task):
        db.close()
        abort(403)
    runs = db.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC",
        (task_id,),
    ).fetchall()
    db.close()
    return render_template("task_runs.html", task=task, runs=runs)


# ── Run detail / live output ───────────────────────────────────────────────────

@app.route("/runs/<int:run_id>")
@login_required
def run_detail(run_id):
    db   = get_db()
    run  = db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,)).fetchone()
    task = None
    if run:
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if not own_task_or_admin(task):
            db.close()
            abort(403)
    db.close()
    return render_template("run_output.html", run=run, task=task)


@app.route("/runs/<int:run_id>/status")
@login_required
def run_status(run_id):
    db  = get_db()
    run = db.execute(
        "SELECT tr.status, tr.output, tr.finished_at, t.user_id "
        "FROM task_runs tr JOIN tasks t ON t.id = tr.task_id WHERE tr.id = ?",
        (run_id,),
    ).fetchone()
    db.close()
    if not run:
        return jsonify({"status": "not_found"}), 404
    if not current_user.is_admin and run["user_id"] != current_user.id:
        abort(403)
    return jsonify({
        "status":      run["status"],
        "output":      run["output"],
        "finished_at": run["finished_at"],
    })


# ── Entry point ────────────────────────────────────────────────────────────────

def _scheduler_tick():
    """Called every minute. Launch any scheduled task whose next_run_at is due."""
    db = get_db()
    try:
        due = db.execute(
            "SELECT id FROM tasks "
            "WHERE schedule_enabled = 1 "
            "  AND next_run_at IS NOT NULL "
            "  AND next_run_at <= datetime('now') "
            "  AND (last_run_status IS NULL OR last_run_status != 'running')"
        ).fetchall()
        for row in due:
            task_id = row["id"]
            # Advance next_run_at before launching so a slow run doesn't re-trigger
            db.execute(
                "UPDATE tasks SET next_run_at = datetime(next_run_at, '+' || schedule_interval || ' minutes') "
                "WHERE id = ?",
                (task_id,),
            )
            db.commit()
            launch_task(task_id)
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(_scheduler_tick, "interval", minutes=1)
    scheduler.start()
    try:
        app.run(debug=False, port=5000)
    finally:
        scheduler.shutdown()
