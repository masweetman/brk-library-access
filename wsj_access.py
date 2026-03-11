"""
Berkeley Public Library - Wall Street Journal Access Automation
Uses injected cookies from a real browser session for WSJ authentication.

Setup (one-time):
    1. Install the "Cookie-Editor" extension in Chrome:
       https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
    2. Log into wsj.com manually in your real Chrome browser
    3. Navigate to wsj.com, open Cookie-Editor, click "Export" -> "Export as JSON"
    4. Save the exported JSON as wsj_cookies.json in the same folder as this script

Requirements:
    pip install playwright
    playwright install chrome
"""

import configparser
import json
import os
import random
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Try to import playwright-stealth; fall back to manual patches if not installed
try:
    from playwright_stealth import Stealth
    USE_STEALTH_LIB = True
except ImportError:
    USE_STEALTH_LIB = False
    print("[WARN] playwright-stealth not installed. Using manual stealth patches.")
    print("[WARN] Install with: pip install playwright-stealth")

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE  = Path(os.environ.get("BRK_CONFIG_FILE",  Path(__file__).parent / "config.ini"))
COOKIES_FILE = Path(os.environ.get("BRK_COOKIES_FILE", Path(__file__).parent / "wsj_cookies.json"))
FORM_URL     = "https://services.berkeleypubliclibrary.org/wsj_access.php"

# ── Stealth JS ────────────────────────────────────────────────────────────────

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
    get: () => { const a = [1,2,3,4,5]; a.__proto__ = PluginArray.prototype; return a; }
});
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => { const a = [1,2,3]; a.__proto__ = MimeTypeArray.prototype; return a; }
});
Object.defineProperty(navigator, 'languages',           { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8 });
Object.defineProperty(navigator, 'userAgent', {
    get: () => navigator.userAgent.replace('HeadlessChrome', 'Chrome'),
});
Object.defineProperty(screen, 'width',       { get: () => 1280 });
Object.defineProperty(screen, 'height',      { get: () => 800  });
Object.defineProperty(screen, 'availWidth',  { get: () => 1280 });
Object.defineProperty(screen, 'availHeight', { get: () => 800  });
Object.defineProperty(screen, 'colorDepth',  { get: () => 24   });
Object.defineProperty(screen, 'pixelDepth',  { get: () => 24   });
window.outerWidth  = 1280;
window.outerHeight = 800;
const _origPermQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
    p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _origPermQuery(p)
);
window.chrome = { runtime: {} };
const _origContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
    get: function() {
        const win = _origContentWindow.get.call(this);
        try { Object.defineProperty(win.navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
        return win;
    }
});
const _getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return _getParam.call(this, p);
};
"""


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
        print("[INFO]  Export your WSJ cookies using Cookie-Editor and save as wsj_cookies.json")
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


def human_delay(min_ms: int, max_ms: int):
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    cfg = load_config(CONFIG_FILE)

    card_number   = cfg.get("credentials", "library_card_number").strip()
    last_name     = cfg.get("credentials", "last_name").strip()
    headless      = cfg.getboolean("browser", "headless",    fallback=True)
    timeout       = cfg.getint("browser",    "timeout",      fallback=30000)
    user_data_dir = cfg.get("browser",       "user_data_dir").strip()
    delay_min     = cfg.getint("browser",    "delay_min_ms", fallback=300)
    delay_max     = cfg.getint("browser",    "delay_max_ms", fallback=900)
    slow_mo       = cfg.getint("browser",    "slow_mo_ms",   fallback=100)

    if not card_number or not last_name:
        print("[ERROR] Please fill in library_card_number and last_name in config.ini")
        sys.exit(1)

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    cookies = load_cookies(COOKIES_FILE)
    print(f"[INFO] Loaded {len(cookies)} cookies from {COOKIES_FILE.name}")
    print(f"[INFO] Loading form: {FORM_URL}")
    print(f"[INFO] Headless: {headless} | Timeout: {timeout}ms | SlowMo: {slow_mo}ms")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            channel="chrome",
            slow_mo=slow_mo,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )

        # Apply stealth — use library if available, else fall back to manual script
        if USE_STEALTH_LIB:
            stealth = Stealth(navigator_webdriver=False)
            stealth.apply_stealth_sync(context)
        else:
            context.add_init_script(STEALTH_SCRIPT)

        # Inject WSJ cookies so the partner handoff lands in an authenticated session
        context.add_cookies(cookies)
        print("[INFO] Cookies injected.")

        page = context.new_page()
        page.set_default_timeout(timeout)

        try:
            # ── Step 1: Load the BPL WSJ form ────────────────────────────────
            page.goto(FORM_URL, wait_until="domcontentloaded")
            print("[INFO] BPL WSJ form loaded.")
            human_delay(delay_min, delay_max)

            # ── Step 2: Fill library card number ─────────────────────────────
            page.locator("input[name='barcode']").fill(card_number)
            print("[INFO] Filled library card number.")
            human_delay(delay_min, delay_max)

            # ── Step 3: Fill last name ────────────────────────────────────────
            page.locator("input[name='lastname']").fill(last_name)
            print("[INFO] Filled last name.")
            human_delay(delay_min, delay_max)

            # ── Step 4: Click Proceed ─────────────────────────────────────────
            page.locator("input[type='submit'][value='Proceed']").click()
            print("[INFO] Clicked Proceed. Waiting for partner link page...")
            page.wait_for_load_state("domcontentloaded")
            print(f"[INFO] Landed on: {page.url}")
            human_delay(delay_min, delay_max)

            # ── Step 5: Navigate directly to the partner.wsj.com URL ──────────
            # Re-inject cookies so they are present when wsj.com loads.
            context.add_cookies(cookies)
            print("[INFO] Cookies re-injected before WSJ navigation.")

            print("[INFO] Looking for WSJ partner link...")
            partner_link = page.locator("a[href*='partner.wsj.com']")
            partner_link.wait_for(state="visible")
            partner_url = partner_link.get_attribute("href")
            print(f"[INFO] Found partner URL: {partner_url}")
            human_delay(delay_min, delay_max)

            # Click the link rather than calling goto() so the browser sends
            # the correct Referer header — partner.wsj.com checks it.
            print("[INFO] Clicking partner link...")
            with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout):
                partner_link.click()
            print(f"[INFO] DOM loaded. URL: {page.url}")

            # Don't wait for networkidle — WSJ's SPA keeps background requests
            # running and it may never fire. Wait for the first form element instead.

            # ── Step 6a: Uncheck email subscription checkbox ──────────────────
            print("[INFO] Waiting for registration form...")
            email_sub = page.locator("#main > div > div > div > div.container > div > div:nth-child(2) > div:nth-child(3) > div:nth-child(1) > div")
            email_sub.wait_for(state="visible", timeout=timeout)
            print(f"[INFO] Registration form ready. URL: {page.url}")
            email_sub.click()
            print("[INFO] Clicked email subscription checkbox.")
            human_delay(delay_min, delay_max)

            # ── Step 6b: Check terms acceptance checkbox ──────────────────────
            print("[INFO] Checking terms acceptance checkbox...")
            terms_cb = page.locator("#main > div > div > div > div.container > div > div:nth-child(2) > div:nth-child(3) > div:nth-child(2) > div")
            terms_cb.wait_for(state="visible")
            terms_cb.click()
            print("[INFO] Clicked terms acceptance checkbox.")
            human_delay(delay_min, delay_max)

            # ── Step 6c: Click Register ───────────────────────────────────────
            print("[INFO] Clicking Register button...")
            register_btn = page.locator("#main > div > div > div > div.container > div > div.row > div > button")
            register_btn.wait_for(state="visible")
            human_delay(delay_min, delay_max)
            register_btn.click()
            print("[INFO] Clicked Register. Waiting for next page...")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=timeout)
            print(f"[SUCCESS] Done. Final URL: {page.url}")

            # Pause so the page is visible before the browser closes
            print("[INFO] Waiting 5 seconds...")
            time.sleep(5)

        except PlaywrightTimeoutError:
            print("[ERROR] Timed out waiting for a page element or navigation.")
            print("[INFO]  If cookies are expired, re-export them from Cookie-Editor and replace wsj_cookies.json.")
            sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] Unexpected error: {exc}")
            raise
        finally:
            context.close()


if __name__ == "__main__":
    run()
