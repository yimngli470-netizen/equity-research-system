"""Headless-browser rendered fetch (option 1) — the fallback for IR sites a static GET can't read.

Many modern IR pages are Q4-style JS apps and/or sit behind bot-protection that STALLS a plain httpx
request (ISRG, UBER, FIG all time out). A real headless Chromium executes the JS and presents a
genuine browser fingerprint, so it gets the rendered HTML where httpx gets nothing.

Used only as a fallback (httpx is tried first and is far cheaper). Chromium is installed in the
Docker image (`playwright install chromium`); if it's somehow unavailable, the import fails and the
caller degrades gracefully to "no transcript".
"""

import logging

logger = logging.getLogger(__name__)


async def fetch_rendered(url: str, user_agent: str, timeout: float = 45.0) -> bytes | None:
    """Return the fully-rendered HTML bytes for `url`, or None on failure.

    Launches headless Chromium, navigates, waits for the network to settle (so JS-injected content
    and links are present), and returns `page.content()`. Bounded by `timeout` seconds.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception:
        logger.warning("[ir.render] playwright not installed — cannot render %s", url)
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                # --no-sandbox is required when running as root in the container; the rest are the
                # standard low-resource container flags.
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1366, "height": 900},
                    locale="en-US",
                )
                page = await ctx.new_page()
                # "domcontentloaded" first (fast), then settle for late JS-injected links.
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass  # networkidle can never fire on chatty IR pages — the DOM is enough
                html = await page.content()
                return html.encode("utf-8", "ignore")
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("[ir.render] rendered fetch failed for %s: %s", url, str(e)[:160])
        return None
