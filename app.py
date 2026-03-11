from flask import Flask, jsonify, redirect, render_template, request, url_for

from db import get_db, init_db
from runner import launch_task

app = Flask(__name__)


# ── Configuration page ─────────────────────────────────────────────────────────

@app.route("/config", methods=["GET", "POST"])
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
                int(request.form.get("timeout",      15000)),
                int(request.form.get("delay_min_ms",   300)),
                int(request.form.get("delay_max_ms",   900)),
                int(request.form.get("slow_mo_ms",     100)),
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
def tasks():
    db   = get_db()
    rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template("tasks.html", tasks=rows)


# ── New task ───────────────────────────────────────────────────────────────────

@app.route("/tasks/new", methods=["GET", "POST"])
def task_new():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """INSERT INTO tasks
                (name, access_type, library_card_number, library_last_name,
                 access_email, access_password, access_cookies)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form.get("name", "").strip(),
                request.form["access_type"],
                request.form.get("library_card_number", "").strip(),
                request.form.get("library_last_name",   "").strip(),
                request.form.get("access_email",        "").strip(),
                request.form.get("access_password",     ""),
                request.form.get("access_cookies",      "").strip(),
            ),
        )
        db.commit()
        db.close()
        return redirect(url_for("tasks"))
    return render_template("task_form.html", task=None)


# ── Edit task ──────────────────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def task_edit(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        db.close()
        return redirect(url_for("tasks"))

    if request.method == "POST":
        db.execute(
            """UPDATE tasks SET
                name                = ?,
                access_type         = ?,
                library_card_number = ?,
                library_last_name   = ?,
                access_email        = ?,
                access_password     = ?,
                access_cookies      = ?
               WHERE id = ?""",
            (
                request.form.get("name", "").strip(),
                request.form["access_type"],
                request.form.get("library_card_number", "").strip(),
                request.form.get("library_last_name",   "").strip(),
                request.form.get("access_email",        "").strip(),
                request.form.get("access_password",     ""),
                request.form.get("access_cookies",      "").strip(),
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
def task_delete(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    db.close()
    return redirect(url_for("tasks"))


# ── Run task ───────────────────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/run", methods=["POST"])
def task_run(task_id):
    run_id = launch_task(task_id)
    return redirect(url_for("run_detail", run_id=run_id))


# ── Run history for a task ─────────────────────────────────────────────────────

@app.route("/tasks/<int:task_id>/runs")
def task_runs(task_id):
    db   = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    runs = db.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC",
        (task_id,),
    ).fetchall()
    db.close()
    return render_template("task_runs.html", task=task, runs=runs)


# ── Run detail / live output ───────────────────────────────────────────────────

@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    db   = get_db()
    run  = db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,)).fetchone()
    task = (
        db.execute("SELECT * FROM tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if run else None
    )
    db.close()
    return render_template("run_output.html", run=run, task=task)


@app.route("/runs/<int:run_id>/status")
def run_status(run_id):
    db  = get_db()
    run = db.execute(
        "SELECT status, output, finished_at FROM task_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    db.close()
    if not run:
        return jsonify({"status": "not_found"}), 404
    return jsonify({
        "status":      run["status"],
        "output":      run["output"],
        "finished_at": run["finished_at"],
    })


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
