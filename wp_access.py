"""
Berkeley Public Library - Washington Post Access Automation
Uses injected cookies from a real browser session to bypass bot detection.

Setup (one-time):
    1. Install the "Cookie-Editor" extension in Chrome:
       https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
    2. Log into washingtonpost.com manually in your real Chrome browser
    3. Navigate to washingtonpost.com, open Cookie-Editor, click "Export" -> "Export as JSON"
    4. Save the exported JSON as wp_cookies.json in the same folder as this script

Requirements:
    pip install playwright
    playwright install chrome
"""

import configparser
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE  = Path(__file__).parent / "config.ini"
COOKIES_FILE = Path(__file__).parent / "wp_cookies.json"
START_URL    = "https://www.washingtonpost.com/subscribe/signin/special-offers/?s_oe=SPECIALOFFER_BERKELEYPL"


def load_config(path: Path) -> configparser.ConfigParser:
    if not path.exists():
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def load_cookies(path: Path) -> list:
    if not path.exists():
        print(f"[ERROR] Cookie file not found: {path}")
        print("[INFO]  Export your WP cookies using Cookie-Editor and save as wp_cookies.json")
        sys.exit(1)
    with open(path) as f:
        cookies = json.load(f)

    valid_same_site = {"Strict", "Lax", "None"}
    for cookie in cookies:
        if cookie.get("sameSite") not in valid_same_site:
            cookie["sameSite"] = "Lax"
        cookie.setdefault("secure",   False)
        cookie.setdefault("httpOnly", False)
        for key in ["hostOnly", "session", "storeId", "id"]:
            cookie.pop(key, None)

    return cookies


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    cfg = load_config(CONFIG_FILE)

    headless      = cfg.getboolean("browser", "headless",    fallback=True)
    timeout       = cfg.getint("browser",    "timeout",      fallback=30000)
    user_data_dir = cfg.get("browser",       "user_data_dir").strip()

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    cookies = load_cookies(COOKIES_FILE)
    print(f"[INFO] Loaded {len(cookies)} cookies from {COOKIES_FILE.name}")
    print(f"[INFO] Headless: {headless} | Timeout: {timeout}ms")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )

        # Inject cookies before any navigation so WP sees an authenticated session
        context.add_cookies(cookies)
        print("[INFO] Cookies injected.")

        page = context.new_page()
        page.set_default_timeout(timeout)

        try:
            # ── Step 1: Navigate to the WP special offer page ─────────────────
            print(f"[INFO] Navigating to {START_URL}...")
            page.goto(START_URL, wait_until="domcontentloaded")
            print(f"[INFO] Page loaded. URL: {page.url}")

            # ── Step 2: Click "Continue to today's news" ──────────────────────
            print("[INFO] Waiting for Continue button...")
            continue_btn = page.locator("button[data-test-id='continue-reading-btn']")
            continue_btn.wait_for(state="visible")
            continue_btn.click()
            print("[INFO] Clicked 'Continue to today's news'.")

            page.wait_for_load_state("domcontentloaded")
            print(f"[SUCCESS] Done. Final URL: {page.url}")

        except PlaywrightTimeoutError:
            print("[ERROR] Timed out waiting for a page element or navigation.")
            print("[INFO]  If cookies are expired, re-export them from Cookie-Editor and replace wp_cookies.json.")
            sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] Unexpected error: {exc}")
            raise
        finally:
            context.close()


if __name__ == "__main__":
    run()
