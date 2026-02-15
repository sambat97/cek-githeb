"""
GitHub Email Registration Checker (Playwright Version)
Mengecek apakah email sudah terdaftar di GitHub menggunakan Playwright.
Headless Chromium — cocok untuk Railway deploy.
"""

import asyncio
import logging
import random
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


async def check_email(page, email: str) -> str:
    """
    Cek apakah email sudah terdaftar di GitHub via signup page.
    Returns: 'registered', 'available', atau 'error'
    """
    try:
        # Buka halaman signup
        await page.goto("https://github.com/signup", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Cari input email
        email_input = page.locator("input#email, input[name='user[login]'], input[type='email']").first
        await email_input.wait_for(state="visible", timeout=10000)

        # Clear dan isi email
        await email_input.fill("")
        await email_input.type(email, delay=50)
        await page.wait_for_timeout(1000)

        # Trigger validasi — klik di luar atau tekan Tab
        await email_input.press("Tab")
        await page.wait_for_timeout(3000)

        # Cek hasil
        content = await page.content()
        content_lower = content.lower()

        # Cek apakah email sudah terdaftar
        if "already associated" in content_lower or "already been taken" in content_lower:
            return "registered"

        # Cek apakah email valid/available (centang hijau)
        success_el = await page.query_selector_all(
            "svg.color-fg-success, .color-fg-success, [class*='success'] svg, .octicon-check"
        )
        if success_el:
            return "available"

        # Cek apakah password field aktif (berarti email diterima)
        try:
            pwd_field = page.locator("input[type='password']").first
            if await pwd_field.is_visible():
                return "available"
        except Exception:
            pass

        # Cek email tidak valid
        if "not a valid email" in content_lower or "not valid" in content_lower:
            return "invalid"

        # Default: tidak bisa ditentukan
        return "error"

    except Exception as e:
        logger.error(f"Error cek {email}: {str(e)[:100]}")
        return "error"


def parse_entries(text: str) -> list[tuple[str, str]]:
    """
    Parse text content dari file txt.
    Format: email:password per baris ATAU email saja per baris
    Returns: list of (email, full_line)
    """
    entries = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" in line:
            email = line.split(":")[0].strip()
        else:
            email = line.strip()

        if "@" in email:
            entries.append((email, line))

    return entries


async def check_emails_batch(
    entries: list[tuple[str, str]],
    progress_callback=None,
    delay: float = 2.0,
) -> dict:
    """
    Cek banyak email sekaligus menggunakan Playwright.
    progress_callback: async function(current, total, email, result)
    Returns: dict dengan keys 'registered', 'available', 'invalid', 'error'
    """
    results = {
        "registered": [],
        "available": [],
        "invalid": [],
        "error": [],
    }

    total = len(entries)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )

        # Anti-detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page = await context.new_page()

        try:
            for i, (email, full_line) in enumerate(entries, 1):
                result = await check_email(page, email)

                if result in results:
                    results[result].append(full_line)
                else:
                    results["error"].append(full_line)

                logger.info(f"[{i}/{total}] {email} -> {result}")

                # Callback progress
                if progress_callback:
                    await progress_callback(i, total, email, result)

                # Delay antar pengecekan
                if i < total:
                    jitter = random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay + jitter)

        except Exception as e:
            logger.error(f"Batch error: {e}")
        finally:
            await browser.close()

    return results
