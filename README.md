# BPL Digital Access Automator

A web-based task runner that automates access to digital newspaper subscriptions available to Berkeley Public Library cardholders. Staff members create tasks for patrons through a browser UI; the app handles the browser automation, scheduling, and run history.

Currently supports:
- **New York Times** — library-card authentication flow
- **Washington Post** — cookie injection to bypass bot detection
- **Wall Street Journal** — cookie injection to bypass bot detection

> 🤖 *This project was vibe-coded using [Claude](https://claude.ai) by Anthropic.*

---

## Features

- **Web UI** — manage tasks, users, and settings from any browser
- **Multi-user accounts** — admin and standard staff roles
- **Task scheduling** — run tasks automatically on a configurable interval
- **Cookie expiry tracking** — displays when injected cookies will expire so staff know when to refresh them
- **Run history** — per-task log of every run with live output streaming
- **Proxy support** — route browser automation through a residential proxy

---

## Architecture

```
app.py          Flask web application + APScheduler background scheduler
db.py           SQLite schema, migrations, and password hashing
runner.py       Task execution: builds temp config/cookie files, runs scripts
nytimes_access.py
wp_access.py    Playwright browser automation scripts
wsj_access.py
templates/      Jinja2 HTML templates (Bootstrap 5)
brk_access.db   SQLite database (created on first run)
```

---

## Ubuntu Server + nginx Installation

The following instructions install the app as a systemd service behind an nginx reverse proxy on Ubuntu 22.04 or 24.04.

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv git nginx
```

If Python 3.13 is not in the default apt repos, add the deadsnakes PPA first:

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv
```

Install Google Chrome (required by Playwright):

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb
```

### 2. Create a dedicated system user

```bash
sudo useradd --system --create-home --shell /bin/bash brkaccess
```

### 3. Clone the repository

```bash
sudo -u brkaccess git clone https://github.com/YOUR_ORG/brk-library-access.git \
    /home/brkaccess/brk-library-access
cd /home/brkaccess/brk-library-access
```

### 4. Create a virtual environment and install dependencies

```bash
sudo -u brkaccess python3.13 -m venv /home/brkaccess/brk-library-access/.venv
sudo -u brkaccess /home/brkaccess/brk-library-access/.venv/bin/pip install \
    --upgrade pip
sudo -u brkaccess /home/brkaccess/brk-library-access/.venv/bin/pip install \
    -r /home/brkaccess/brk-library-access/requirements.txt
```

Install the Playwright browser (Chrome):

```bash
sudo -u brkaccess /home/brkaccess/brk-library-access/.venv/bin/playwright \
    install chrome
```

### 5. Generate a secret key

The app reads `SECRET_KEY` from the environment. Generate a strong random value and note it down — you will use it in the next step:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Create the systemd service

Create `/etc/systemd/system/brkaccess.service`:

```ini
[Unit]
Description=BRK Library Access Web App
After=network.target

[Service]
Type=simple
User=brkaccess
WorkingDirectory=/home/brkaccess/brk-library-access
Environment="SECRET_KEY=PASTE_YOUR_SECRET_KEY_HERE"
ExecStart=/home/brkaccess/brk-library-access/.venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:5000 \
    --access-logfile /var/log/brkaccess/access.log \
    --error-logfile /var/log/brkaccess/error.log \
    "app:app"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create the log directory:

```bash
sudo mkdir -p /var/log/brkaccess
sudo chown brkaccess:brkaccess /var/log/brkaccess
```

Install gunicorn into the venv:

```bash
sudo -u brkaccess /home/brkaccess/brk-library-access/.venv/bin/pip install gunicorn
```

Initialise the database (creates `brk_access.db` with a default `admin` / `password` account):

```bash
sudo -u brkaccess bash -c "cd /home/brkaccess/brk-library-access && \
    .venv/bin/python -c 'from db import init_db; init_db()'"
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable brkaccess
sudo systemctl start brkaccess
sudo systemctl status brkaccess
```

### 7. Configure nginx

Create `/etc/nginx/sites-available/brkaccess`:

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    # Increase timeout for long-running task launches
    proxy_read_timeout 120s;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and reload nginx:

```bash
sudo ln -s /etc/nginx/sites-available/brkaccess /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 8. (Recommended) Add HTTPS with Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN
```

Certbot will update the nginx config automatically and set up certificate auto-renewal.

### 9. First login and initial setup

Open `http://YOUR_DOMAIN_OR_IP` in a browser and log in with:

- **Username:** `admin`
- **Password:** `password`

**Change the admin password immediately** — click the username menu in the top-right navbar and choose **Profile**.

Then visit **Configuration** to set:
- Browser profile directory (defaults to `~/.bpl_browser_profile`)
- Proxy settings (if your server needs one)
- Headless mode and timing parameters

---

## Updating

```bash
cd /home/brkaccess/brk-library-access
sudo -u brkaccess git pull
sudo -u brkaccess .venv/bin/pip install -r requirements.txt
# init_db() is idempotent and runs migrations automatically
sudo -u brkaccess bash -c ".venv/bin/python -c 'from db import init_db; init_db()'"
sudo systemctl restart brkaccess
```

---

## Using the Web UI

### Tasks

Each **task** represents one patron's access configuration for one publication.

| Field | Description |
|-------|-------------|
| Name | A label for the task (e.g. "Smith — NYT March") |
| Publication | `nyt`, `wp`, or `wsj` |
| Library card number | The patron's BPL card barcode |
| Last name | The patron's last name as on their library account |
| Email / Password | The patron's publication account credentials (NYT only requires these) |
| Cookies (JSON) | Cookie-Editor JSON export for WP and WSJ |
| Schedule | Enable automatic runs and set the interval in minutes |

Tasks are private to the staff member who created them. Admins can see and edit all tasks.

### Running a task manually

Click **Run** on any task. You are taken to a live output page that polls the server until the run finishes. The run is recorded in the task's history.

### Scheduling

Enable **Run automatically** on a task and set the interval in minutes (minimum 1). New tasks default to **enabled at 1441 minutes** (~24 hours). The background scheduler checks every minute and launches any task whose `next_run_at` has passed. The next run time advances automatically after each launch.

### Cookie expiry

When you paste a Cookie-Editor JSON export the app reads the first cookie's `expirationDate` and displays it in the task list, so staff know when cookies need to be refreshed.

### Profile

Every user has a **Profile** page (navbar → username → Profile) where they can change their own password. It shows their username and role (Admin or User).

### Users (admin only)

Admins can create, rename, change passwords for, and delete staff accounts. A standard (non-admin) account can manage and run its own tasks but cannot access the Users or Configuration pages. Any user can change their own password via their Profile.

### Configuration (admin only)

| Setting | Description |
|---------|-------------|
| Proxy server | `host:port` of a proxy for all browser automation |
| Proxy username / password | Proxy credentials if required |
| Browser profile directory | Path where Playwright stores session state between runs |
| Headless | Run the browser invisibly (recommended for servers) |
| Timeout (ms) | Maximum wait time for any page element |
| Min / Max delay (ms) | Random inter-action delay range to mimic human timing |
| Slow-mo (ms) | Fixed additional delay applied to every browser action |

---

## Exporting Cookies (WP and WSJ)

1. Install [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) in Chrome.
2. Log into [washingtonpost.com](https://washingtonpost.com) or [wsj.com](https://wsj.com) in your real browser.
3. Open Cookie-Editor on that tab and click **Export → Export as JSON**.
4. Copy the JSON and paste it into the **Cookies (JSON)** field when creating or editing a task.

Cookies typically expire after 30–90 days. The task list shows the expiry date — refresh them before then.

---

## Troubleshooting

**Task fails immediately / blank output**
Check `/var/log/brkaccess/error.log`. A common cause is Playwright not finding Chrome — confirm `playwright install chrome` was run as the `brkaccess` user.

**Washington Post or WSJ task fails**
Cookies have probably expired. Re-export from Cookie-Editor and edit the task to paste in the new JSON.

**Browser hangs and task times out after 3 minutes**
Increase **Timeout** in Configuration, or switch **Headless** off temporarily (requires a desktop environment), set `slow_mo_ms = 500`, and re-run to watch what gets stuck.

**Service won't start**
Check `sudo journalctl -u brkaccess -n 50` for the error. A missing `SECRET_KEY` or incorrect file path in the service unit are the most common causes.

**nginx returns 502 Bad Gateway**
The gunicorn process is not running. Check `sudo systemctl status brkaccess`.

---

## Running tests

```bash
.venv/bin/python -m pytest tests/ -v
```

The test suite has 224 tests covering unit, integration, and user-story scenarios. No external services or browser are required — all browser calls are mocked.
