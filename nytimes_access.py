"""
Berkeley Public Library - NY Times Access Form Automation
Fills out the library card authentication form at:
https://services.berkeleypubliclibrary.org/nytimes_access.php

Requirements:
    pip install playwright
    playwright install chrome
"""

import configparser
import random
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.ini"
FORM_URL = "https://services.berkeleypubliclibrary.org/nytimes_access.php"

# ── Stealth JS ────────────────────────────────────────────────────────────────
# Injected into every page before any scripts run. Patches the properties
# that bot detectors most commonly probe.

STEALTH_SCRIPT = """
// Mask the webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof a realistic plugin list
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Spoof a realistic language list
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Remove the 'HeadlessChrome' string from the user agent reported to JS
Object.defineProperty(navigator, 'userAgent', {
    get: () => navigator.userAgent.replace('HeadlessChrome', 'Chrome'),
});

// Patch permission query to behave like a real browser
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// Spoof chrome runtime object present in real Chrome
window.chrome = { runtime: {} };
"""


def load_config(path: Path) -> configparser.ConfigParser:
    if not path.exists():
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def human_delay(min_ms: int, max_ms: int):
    """Pause for a random duration to mimic human interaction speed."""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    cfg = load_config(CONFIG_FILE)

    card_number   = cfg.get("credentials", "library_card_number").strip()
    last_name     = cfg.get("credentials", "last_name").strip()
    nyt_email     = cfg.get("nyt", "nyt_email").strip()
    nyt_password  = cfg.get("nyt", "nyt_password").strip()
    headless      = cfg.getboolean("browser", "headless", fallback=True)
    timeout       = cfg.getint("browser", "timeout", fallback=15000)
    user_data_dir = cfg.get("browser", "user_data_dir").strip()
    delay_min     = cfg.getint("browser", "delay_min_ms", fallback=300)
    delay_max     = cfg.getint("browser", "delay_max_ms", fallback=900)

    if not card_number or not last_name:
        print("[ERROR] Please fill in library_card_number and last_name in config.ini")
        sys.exit(1)
    if not nyt_email or not nyt_password:
        print("[ERROR] Please fill in nyt_email and nyt_password in config.ini")
        sys.exit(1)

    # Ensure the persistent profile directory exists
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Loading form: {FORM_URL}")
    print(f"[INFO] Headless: {headless} | Timeout: {timeout}ms")
    print(f"[INFO] Browser profile: {user_data_dir}")

    with sync_playwright() as p:
        # Use a persistent context so session cookies are saved between runs,
        # and target the real Chrome install to avoid headless fingerprinting.
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
        )

        # Inject stealth patches into every page before any scripts run
        context.add_init_script(STEALTH_SCRIPT)

        page = context.new_page()
        page.set_default_timeout(timeout)

        try:
            # ── Step 1: Fill and submit the library card form ─────────────────
            page.goto(FORM_URL, wait_until="domcontentloaded")
            print("[INFO] Page loaded.")
            human_delay(delay_min, delay_max)

            page.locator("input[name='barcode']").fill(card_number)
            print("[INFO] Filled library card number.")
            human_delay(delay_min, delay_max)

            page.locator("input[name='lastname']").fill(last_name)
            print("[INFO] Filled last name.")
            human_delay(delay_min, delay_max)

            page.locator("input[type='submit'][value='Proceed']").click()
            print("[INFO] Clicked Proceed. Waiting for next page...")

            page.wait_for_load_state("networkidle")
            print(f"[INFO] Landed on: {page.url}")

            # Check for credential errors before going further
            body_text = page.inner_text("body").lower()
            error_hints = ["invalid", "not found", "incorrect", "error", "try again"]
            if any(hint in body_text for hint in error_hints):
                print("[WARNING] The page may contain an error — check your credentials in config.ini.")
                sys.exit(1)

            # ── Step 2: Fill gift code and click Redeem ──────────────────────
            print("[INFO] Waiting for gift code page to load...")
            page.wait_for_load_state("networkidle")
            print(f"[INFO] Landed on: {page.url}")

            # Wait for the Redeem button to appear — the URL will have the
            # gift_code query param by this point
            print("[INFO] Waiting for Redeem button...")
            redeem = page.locator("button[data-testid='btn-redeem'][type='submit']")
            redeem.wait_for(state="visible")

            # Now extract gift_code from the URL
            # e.g. https://...?gift_code=51c231ece107414f
            from urllib.parse import urlparse, parse_qs
            parsed    = urlparse(page.url)
            params    = parse_qs(parsed.query)
            gift_code = params.get("gift_code", [None])[0]

            if not gift_code:
                print("[ERROR] Could not find 'gift_code' in the URL:", page.url)
                sys.exit(1)

            print(f"[INFO] Found gift code: {gift_code}")

            # Fill the gift code into the input field
            code_input = page.locator("input[data-testid='input-code'][name='code']")
            code_input.wait_for(state="visible")
            human_delay(delay_min, delay_max)
            code_input.fill(gift_code)
            print("[INFO] Filled gift code into input field.")
            human_delay(delay_min, delay_max)

            # Click Redeem
            print("[INFO] Waiting 5 seconds before clicking Redeem...")
            time.sleep(5)
            redeem.click()
            print("[INFO] Clicked Redeem. Waiting for NYT login page...")

            # ── Step 4: Wait on the NYT login page ────────────────────────────
            page.wait_for_load_state("networkidle")
            print(f"[INFO] Landed on: {page.url}")

            # If the persistent session already has a valid NYT login, the page
            # may skip straight past the login form — detect that and exit early.
            if "nytimes.com" in page.url and "login" not in page.url:
                print("[SUCCESS] Already logged in via saved session. Done!")
                return

            # ── Step 5: Enter NYT email and click Continue ────────────────────
            print("[INFO] Entering NYT email...")
            email_field = page.locator("input#email[name='email'][type='email']")
            email_field.wait_for(state="visible")
            human_delay(delay_min, delay_max)
            email_field.fill(nyt_email)
            human_delay(delay_min, delay_max)

            page.locator("button[data-testid='submit-email']").click()
            print("[INFO] Clicked Continue. Waiting for password page...")

            page.wait_for_load_state("networkidle")
            print(f"[INFO] Landed on: {page.url}")

            # ── Step 6: Enter NYT password and click Log in ───────────────────
            print("[INFO] Entering NYT password...")
            password_field = page.locator("input#password[name='password'][type='password']")
            password_field.wait_for(state="visible")
            human_delay(delay_min, delay_max)
            password_field.fill(nyt_password)
            human_delay(delay_min, delay_max)

            page.locator("button[data-testid='submit-password-button']").click()
            print("[INFO] Clicked Log in. Waiting for final page...")

            page.wait_for_load_state("networkidle")
            print(f"[SUCCESS] Done. Final URL: {page.url}")

            # Pause so the page is visible before the browser closes
            print("[INFO] Waiting 5 seconds...")
            time.sleep(5)

        except PlaywrightTimeoutError:
            print("[ERROR] Timed out waiting for a page element or navigation.")
            sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] Unexpected error: {exc}")
            raise
        finally:
            context.close()


if __name__ == "__main__":
    run()
