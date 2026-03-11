"""
Task runner — builds a temporary config.ini + cookies file per task and
executes the appropriate access script as a subprocess. Results are
persisted to the task_runs table in the database.
"""

import configparser
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from db import get_db

# ── Script / file mappings ─────────────────────────────────────────────────────

SCRIPTS: dict[str, Path] = {
    "nyt": Path(__file__).parent / "nytimes_access.py",
    "wp":  Path(__file__).parent / "wp_access.py",
    "wsj": Path(__file__).parent / "wsj_access.py",
}

COOKIE_FILENAMES: dict[str, str] = {
    "nyt": "nytimes_cookies.json",
    "wp":  "wp_cookies.json",
    "wsj": "wsj_cookies.json",
}

# wp_access.py is the only script that reads credentials from config
_WP_SECTION = "washingtonpost"


# ── Public API ─────────────────────────────────────────────────────────────────

def launch_task(task_id: int) -> int:
    """
    Create a task_run record (status='running'), start execution in a
    background thread, and return the run_id immediately.
    """
    db = get_db()
    try:
        run_id = db.execute(
            "INSERT INTO task_runs (task_id, status, output) VALUES (?, 'running', '')",
            (task_id,),
        ).lastrowid
        db.execute(
            "UPDATE tasks SET last_run_at = datetime('now'), last_run_status = 'running' WHERE id = ?",
            (task_id,),
        )
        db.commit()
    finally:
        db.close()

    thread = threading.Thread(target=_run_task, args=(task_id, run_id), daemon=True)
    thread.start()
    return run_id


# ── Internal helpers ───────────────────────────────────────────────────────────

def _run_task(task_id: int, run_id: int) -> None:
    db = get_db()
    try:
        task     = db.execute("SELECT * FROM tasks    WHERE id = ?", (task_id,)).fetchone()
        settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        if not task:
            _finish(db, run_id, task_id, "failed", f"[ERROR] Task {task_id} not found.")
            return

        try:
            output, returncode = _execute(task, settings)
            status = "success" if returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output, status = "[ERROR] Task timed out after 180 seconds.", "failed"
        except Exception as exc:
            output, status = f"[ERROR] {exc}", "failed"

        _finish(db, run_id, task_id, status, output)
    finally:
        db.close()


def _finish(db, run_id: int, task_id: int, status: str, output: str) -> None:
    db.execute(
        "UPDATE task_runs SET finished_at = datetime('now'), status = ?, output = ? WHERE id = ?",
        (status, output, run_id),
    )
    db.execute(
        "UPDATE tasks SET last_run_status = ? WHERE id = ?",
        (status, task_id),
    )
    db.commit()


def _execute(task, settings) -> tuple[str, int]:
    """Build a temp config + cookies file and run the script. Returns (output, returncode)."""
    access_type = task["access_type"]

    # ── Build config.ini ──────────────────────────────────────────────────────
    cfg = configparser.ConfigParser()
    cfg["credentials"] = {
        "library_card_number": task["library_card_number"],
        "last_name":           task["library_last_name"],
    }
    # Only wp_access.py reads publication credentials from config
    if access_type == "wp":
        cfg[_WP_SECTION] = {
            "wp_email":    task["access_email"],
            "wp_password": task["access_password"],
        }
    cfg["proxy"] = {
        "server":   settings["proxy_server"]   or "",
        "username": settings["proxy_username"] or "",
        "password": settings["proxy_password"] or "",
    }
    user_data_dir = settings["user_data_dir"] or str(Path.home() / ".bpl_browser_profile")
    cfg["browser"] = {
        "user_data_dir": user_data_dir,
        "headless":      "true" if settings["headless"] else "false",
        "timeout":       str(settings["timeout"]),
        "delay_min_ms":  str(settings["delay_min_ms"]),
        "delay_max_ms":  str(settings["delay_max_ms"]),
        "slow_mo_ms":    str(settings["slow_mo_ms"]),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path  = Path(tmpdir)
        config_path  = tmpdir_path / "config.ini"
        cookies_path = tmpdir_path / COOKIE_FILENAMES[access_type]

        with open(config_path, "w") as f:
            cfg.write(f)

        cookies_data = (task["access_cookies"] or "").strip()
        cookies_path.write_text(cookies_data if cookies_data else "[]")

        env = {
            **os.environ,
            "BRK_CONFIG_FILE":  str(config_path),
            "BRK_COOKIES_FILE": str(cookies_path),
        }

        result = subprocess.run(
            [sys.executable, str(SCRIPTS[access_type])],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    parts = [result.stdout]
    if result.returncode != 0:
        parts.append(f"\n[Exit code: {result.returncode}]")
    if result.stderr:
        parts.append("\n[STDERR]\n" + result.stderr)

    return "".join(parts), result.returncode
