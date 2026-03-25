"""Automate BSale login via Playwright to obtain the stock.bsale.app session cookie.

Flow (mirrors the manual browser flow):
  1. Login at account.bsale.dev with email/password
  2. Select the SILK PERFUMES company (cpn 67758)
  3. Navigate to the Stock module → stock.bsale.app sets its session cookie
  4. Return the bsale-session cookie value
"""

import logging
import os

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

ACCOUNT_URL = "https://account.bsale.dev"
STOCK_URL = "https://stock.bsale.app"
COMPANY_CPN = "67758"


def get_session_cookie(email: str, password: str) -> str:
    """Launch headless Chromium, login to BSale, return the bsale-session cookie.

    Raises RuntimeError if the cookie cannot be obtained.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        )
        context = browser.new_context()
        page = context.new_page()

        # --- Step 1: Login ---
        logger.info("Navigating to BSale login...")
        page.goto(ACCOUNT_URL, wait_until="networkidle")

        page.fill('input[type="email"], input[name="email"]', email)
        page.fill('input[type="password"], input[name="password"]', password)
        page.click('button:has-text("INGRESAR")')

        # Wait for company list to appear
        logger.info("Logging in...")
        page.wait_for_url("**/account/**", timeout=15000)
        page.wait_for_load_state("networkidle")

        # --- Step 2: Select company ---
        logger.info("Selecting company (cpn %s)...", COMPANY_CPN)
        # The "Ingresar" button may open a new tab — listen for popup
        row = page.locator(f"tr:has(td:has-text('{COMPANY_CPN}'))")

        with context.expect_page(timeout=15000) as new_page_info:
            row.locator("button, a").first.click()

        # Switch to the new page (admin dashboard)
        admin_page = new_page_info.value
        admin_page.wait_for_load_state("networkidle")
        logger.info("Admin dashboard loaded: %s", admin_page.url)

        # --- Step 3: Navigate to Stock module ---
        logger.info("Navigating to Stock module...")
        stock_link = admin_page.locator('text=Stock actual').first
        if stock_link.is_visible(timeout=5000):
            # May open yet another tab or navigate in-page
            try:
                with context.expect_page(timeout=10000) as stock_page_info:
                    stock_link.click()
                stock_page = stock_page_info.value
            except Exception:
                # Navigated in same tab
                stock_page = admin_page
        else:
            # Fallback: navigate directly
            admin_page.goto(STOCK_URL, wait_until="networkidle")
            stock_page = admin_page

        stock_page.wait_for_load_state("networkidle")
        logger.info("Stock page loaded: %s", stock_page.url)

        # --- Step 4: Extract the cookie ---
        cookies = context.cookies(STOCK_URL)
        session_cookie = None
        for c in cookies:
            if c["name"] == "bsale-session":
                session_cookie = c["value"]
                break

        browser.close()

    if not session_cookie:
        raise RuntimeError(
            "Could not obtain bsale-session cookie. "
            "The login flow may have changed."
        )

    logger.info("Session cookie obtained successfully.")
    return session_cookie


def get_session_cookie_from_env() -> str:
    """Get session cookie by logging in with credentials from environment variables.

    Uses BSALE_EMAIL and BSALE_PASSWORD from the environment / .env file.
    If BSALE_SESSION_COOKIE is already set (e.g. by the Lambda handler to
    avoid launching Playwright multiple times), returns that directly.
    """
    cached = os.getenv("BSALE_SESSION_COOKIE")
    if cached:
        logger.info("Using cached BSale session cookie from environment.")
        return cached

    email = os.getenv("BSALE_EMAIL")
    password = os.getenv("BSALE_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "ERROR: BSALE_EMAIL and BSALE_PASSWORD must be set in .env file."
        )
    return get_session_cookie(email, password)
