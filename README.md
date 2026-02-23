# BPL Digital Access Automator

Automates access to digital newspaper subscriptions available to Berkeley Public Library cardholders. Instead of manually navigating each publication's authentication flow every day, these scripts handle it for you in seconds.

Currently supports:
- **New York Times** (via `nytimes_access.py`)
- **Washington Post** (via `wp_access.py`)
- **Wall Street Journal** (via `wsj_access.py`)

> 🤖 *This project was vibe-coded using [Claude](https://claude.ai) by Anthropic.*

---

## Requirements

- Ubuntu (or any Linux distro)
- Google Chrome installed
- Python 3.8+

---

## Installation

### 1. Install Google Chrome

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
```

### 2. Install Python dependencies

```bash
pip install playwright
playwright install chrome
```

### 3. Clone or download this project

Place all files in the same directory:

```
bpl-access/
├── config.ini
├── nytimes_access.py
├── wp_access.py
├── wp_cookies.json
├── wsj_access.py
└── wsj_cookies.json
```

### 4. Edit `config.ini`

Open `config.ini` and fill in your details:

```ini
[credentials]
library_card_number = YOUR_LIBRARY_CARD_NUMBER
last_name = YOUR_LAST_NAME

[nyt]
nyt_email = YOUR_NYT_EMAIL
nyt_password = YOUR_NYT_PASSWORD

[washingtonpost]
wp_email = YOUR_WP_EMAIL
wp_password = YOUR_WP_PASSWORD

[wsj]
wsj_email = YOUR_WSJ_EMAIL
wsj_password = YOUR_WSJ_PASSWORD

[browser]
headless = true
timeout = 30000
user_data_dir = /home/YOUR_USERNAME/.bpl_browser_profile
delay_min_ms = 300
delay_max_ms = 900
slow_mo_ms = 100
```

Replace `YOUR_USERNAME` with your actual Linux username (e.g. `/home/john/.bpl_browser_profile`).

---

## Usage

### New York Times

```bash
python nytimes_access.py
```

Navigates to the BPL NYT portal, authenticates with your library card, redeems the gift code, and logs into NYT with your email and password.

### Washington Post

The Washington Post uses cookie-based authentication to bypass bot detection.

**One-time setup:**
1. Install the [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) extension in Chrome
2. Log into [washingtonpost.com](https://washingtonpost.com) in your real Chrome browser
3. Open Cookie-Editor on washingtonpost.com and click **Export → Export as JSON**
4. Save the file as `wp_cookies.json` in the project directory

```bash
python wp_access.py
```

### Wall Street Journal

The Wall Street Journal also uses cookie-based authentication.

**One-time setup:**
1. Install the [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) extension in Chrome
2. Log into [wsj.com](https://wsj.com) in your real Chrome browser
3. Open Cookie-Editor on wsj.com and click **Export → Export as JSON**
4. Save the file as `wsj_cookies.json` in the project directory

```bash
python wsj_access.py
```

---

## Troubleshooting

**Script times out or a page appears blank**
Set `headless = false` in `config.ini` to watch the browser in real time and see where it gets stuck.

**Washington Post or WSJ won't load**
These sites use aggressive bot detection. If the cookie approach stops working, your cookies have likely expired — re-export fresh ones from Cookie-Editor and replace the `.json` file.

**Wrong fields being filled**
Run with `headless = false` and `slow_mo_ms = 500` to slow everything down and watch each interaction.

**Chrome not found**
Make sure Google Chrome (not Chromium) is installed, and that `playwright install chrome` has been run.

---

## Configuration Reference

| Key | Description |
|-----|-------------|
| `library_card_number` | Your BPL library card barcode number |
| `last_name` | Your last name as it appears on your library account |
| `nyt_email` / `nyt_password` | Your NYT account credentials |
| `wp_email` / `wp_password` | Your Washington Post account credentials |
| `wsj_email` / `wsj_password` | Your WSJ account credentials |
| `headless` | `true` to run silently, `false` to watch the browser |
| `timeout` | Max time (ms) to wait for any page element before failing |
| `user_data_dir` | Path where browser session cookies are persisted between runs |
| `delay_min_ms` / `delay_max_ms` | Random delay range between actions (mimics human timing) |
| `slow_mo_ms` | Additional fixed delay (ms) applied to every browser interaction |
