"""
NY Times Access Test Script — Enhanced Anti-Detection
Navigates to the NYT redemption page using comprehensive bot-evasion techniques.

Requirements:
    pip install playwright playwright-stealth
    playwright install chrome

Proxy setup (optional but recommended):
    Add proxy credentials to config.ini under [proxy].
    Use a residential proxy provider such as:
      - Brightdata   https://brightdata.com
      - Oxylabs      https://oxylabs.io
      - Smartproxy   https://smartproxy.com
    Residential proxies rotate IPs and are not flagged as datacenter traffic.
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
COOKIES_FILE = Path(os.environ.get("BRK_COOKIES_FILE", Path(__file__).parent / "nytimes_cookies.json"))
REDEEM_URL   = "https://www.nytimes.com/subscription/redeem/all-access"
GIFT_CODE    = "51c231ece107414f"

# ── Fallback stealth JS (used if playwright-stealth is not installed) ─────────

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver',           { get: () => undefined });
Object.defineProperty(navigator, 'plugins',             { get: () => { const a=[1,2,3,4,5]; a.__proto__=PluginArray.prototype; return a; }});
Object.defineProperty(navigator, 'mimeTypes',           { get: () => { const a=[1,2,3]; a.__proto__=MimeTypeArray.prototype; return a; }});
Object.defineProperty(navigator, 'languages',           { get: () => ['en-US','en'] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8 });
Object.defineProperty(navigator, 'userAgent',           { get: () => navigator.userAgent.replace('HeadlessChrome','Chrome') });
Object.defineProperty(screen, 'width',       { get: () => 1280 });
Object.defineProperty(screen, 'height',      { get: () => 800  });
Object.defineProperty(screen, 'availWidth',  { get: () => 1280 });
Object.defineProperty(screen, 'availHeight', { get: () => 800  });
Object.defineProperty(screen, 'colorDepth',  { get: () => 24   });
Object.defineProperty(screen, 'pixelDepth',  { get: () => 24   });
window.outerWidth = 1280; window.outerHeight = 800;
const _q = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => p.name==='notifications'
    ? Promise.resolve({ state: Notification.permission }) : _q(p);
window.chrome = { runtime: {} };
const _cw = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'contentWindow');
Object.defineProperty(HTMLIFrameElement.prototype,'contentWindow',{get:function(){
    const w=_cw.get.call(this);
    try{Object.defineProperty(w.navigator,'webdriver',{get:()=>undefined})}catch(e){}
    return w;
}});
const _gp = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if(p===37445) return 'Intel Inc.';
    if(p===37446) return 'Intel Iris OpenGL Engine';
    return _gp.call(this,p);
};
"""

# ── Fides stub (prevents blank screen on privacy-gated pages) ────────────────

FIDES_SCRIPT = """
(function() {
    if (typeof window.fidesEmbed !== 'undefined') return;
    var _queue = [];
    window.fidesEmbed = function() { _queue.push(arguments); };
    window.fidesEmbed.queue  = _queue;
    window.fidesEmbed.isStub = true;
    window.__fidesEmbedReady = function(real) {
        window.fidesEmbed = real;
        _queue.forEach(function(a){ real.apply(null,a); });
        _queue.length = 0;
    };
})();
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
        print("[INFO]  Export NYT cookies via Cookie-Editor and save as nytimes_cookies.json")
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


def human_delay(page, min_ms: int = 300, max_ms: int = 900):
    """Random pause using Playwright's internal timer (more realistic than time.sleep)."""
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def move_mouse_naturally(page, target_x: int, target_y: int):
    """
    Move the mouse to a target in a curved arc with random micro-jitter,
    simulating the non-linear path of a real human hand.
    """
    current = page.evaluate("() => ({ x: window.__mouseX || 640, y: window.__mouseY || 400 })")
    cx, cy  = current["x"], current["y"]

    # Bezier control point adds a slight curve to the path
    ctrl_x = (cx + target_x) / 2 + random.randint(-80, 80)
    ctrl_y = (cy + target_y) / 2 + random.randint(-80, 80)
    steps  = random.randint(18, 30)

    for i in range(1, steps + 1):
        t   = i / steps
        # Quadratic bezier interpolation
        x   = int((1-t)**2 * cx + 2*(1-t)*t * ctrl_x + t**2 * target_x)
        y   = int((1-t)**2 * cy + 2*(1-t)*t * ctrl_y + t**2 * target_y)
        # Add subtle per-step jitter
        x  += random.randint(-2, 2)
        y  += random.randint(-2, 2)
        page.mouse.move(x, y)
        page.wait_for_timeout(random.randint(8, 25))

    # Store last position for next call
    page.evaluate(f"() => {{ window.__mouseX = {target_x}; window.__mouseY = {target_y}; }}")


def human_scroll(page):
    """Scroll down the page gradually, like a person reading."""
    total   = random.randint(200, 500)
    scrolled = 0
    while scrolled < total:
        step = random.randint(40, 120)
        page.mouse.wheel(0, step)
        scrolled += step
        page.wait_for_timeout(random.randint(80, 200))


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    cfg = load_config(CONFIG_FILE)

    headless      = cfg.getboolean("browser", "headless",    fallback=False)
    timeout       = cfg.getint("browser",    "timeout",      fallback=30000)
    user_data_dir = cfg.get("browser",       "user_data_dir").strip()
    delay_min     = cfg.getint("browser",    "delay_min_ms", fallback=300)
    delay_max     = cfg.getint("browser",    "delay_max_ms", fallback=900)
    slow_mo       = cfg.getint("browser",    "slow_mo_ms",   fallback=50)

    # Optional residential proxy — set in config.ini [proxy] section
    proxy_server   = cfg.get("proxy", "server",   fallback="").strip()
    proxy_username = cfg.get("proxy", "username", fallback="").strip()
    proxy_password = cfg.get("proxy", "password", fallback="").strip()
    proxy_config   = None
    if proxy_server:
        proxy_config = {"server": proxy_server}
        if proxy_username:
            proxy_config["username"] = proxy_username
            proxy_config["password"] = proxy_password
        print(f"[INFO] Using proxy: {proxy_server}")
    else:
        print("[INFO] No proxy configured. Add one under [proxy] in config.ini for best results.")

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    cookies = load_cookies(COOKIES_FILE)
    print(f"[INFO] Loaded {len(cookies)} cookies from {COOKIES_FILE.name}")
    print(f"[INFO] Headless: {headless} | Timeout: {timeout}ms | SlowMo: {slow_mo}ms")
    print(f"[INFO] Stealth library: {'playwright-stealth' if USE_STEALTH_LIB else 'manual patches'}")

    with sync_playwright() as p:
        launch_args = {
            "user_data_dir": user_data_dir,
            "headless":      headless,
            "channel":       "chrome",
            "slow_mo":       slow_mo,
            "viewport":      {"width": 1280, "height": 800},
            "locale":        "en-US",
            "timezone_id":   "America/Los_Angeles",
            "geolocation":   {"latitude": 37.8716, "longitude": -122.2727},  # Berkeley, CA
            "permissions":   ["geolocation"],
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "extra_http_headers": {
                "Accept-Language":           "en-US,en;q=0.9",
                "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site":            "none",
                "Sec-Fetch-Mode":            "navigate",
                "Sec-Fetch-User":            "?1",
                "Sec-Fetch-Dest":            "document",
            },
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        if proxy_config:
            launch_args["proxy"] = proxy_config

        context = p.chromium.launch_persistent_context(**launch_args)

        # Inject fides stub first — must precede all page scripts
        context.add_init_script(FIDES_SCRIPT)

        # Apply stealth — use library if available, else fall back to manual script
        if USE_STEALTH_LIB:
            stealth = Stealth(navigator_webdriver=False)
            stealth.apply_stealth_sync(context)
        else:
            context.add_init_script(STEALTH_SCRIPT)

        # Inject cookies before first navigation
        context.add_cookies(cookies)
        print("[INFO] Cookies injected.")

        page = context.new_page()
        page.set_default_timeout(timeout)

        try:
            # ── Step 1 & 2: Load page, wait for full execution ────────────────
            print(f"[INFO] Loading {REDEEM_URL} ...")
            page.goto(REDEEM_URL, wait_until="networkidle")
            print(f"[INFO] Page fully loaded. URL: {page.url}")

            # Simulate a person glancing at the page before doing anything
            human_delay(page, delay_min, delay_max)
            human_scroll(page)
            human_delay(page, delay_min, delay_max)

            # ── Step 3: Set the gift code via JS ──────────────────────────────
            print(f"[INFO] Setting gift code: {GIFT_CODE}")
            page.locator("input[name='code']").fill(GIFT_CODE)
            print("[INFO] Gift code set.")
            human_delay(page, delay_min, delay_max)

            # ── Step 4: Move mouse naturally to Redeem button, then click ─────
            print("[INFO] Waiting for Redeem button...")
            redeem = page.locator("button[data-testid='btn-redeem'][type='submit']")
            redeem.wait_for(state="visible")

            # Get button coordinates for realistic mouse movement
            box = redeem.bounding_box()
            if box:
                target_x = int(box["x"] + box["width"]  / 2)
                target_y = int(box["y"] + box["height"] / 2)
                move_mouse_naturally(page, target_x, target_y)
                human_delay(page, 200, 500)

            # Wait 5 seconds before clicking so you can observe the state
            print("[INFO] Waiting 5 seconds before clicking Redeem...")
            time.sleep(5)

            redeem.click()
            print("[INFO] Clicked Redeem.")
            page.wait_for_load_state("domcontentloaded")
            print(f"[INFO] Landed on: {page.url}")

            # ── Step 5: Wait 5 seconds to observe the result ─────────────────
            print("[INFO] Waiting 5 seconds...")
            time.sleep(5)
            print(f"[SUCCESS] Done. Final URL: {page.url}")

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
