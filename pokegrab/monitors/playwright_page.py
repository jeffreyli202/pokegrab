from urllib.parse import quote_plus

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import Monitor


class PlaywrightPageMonitor(Monitor):
    """Page monitor that launches a real Chromium browser to bypass bot detection."""

    url_template: str

    def __init__(self, pause_seconds: float = 2.0):
        self.pause_seconds = pause_seconds
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        from playwright_stealth import stealth_async

        url = self.url_template.format(query=quote_plus(keyword))
        browser = await self._ensure_browser()
        page = await browser.new_page()
        try:
            await stealth_async(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
        finally:
            await page.close()
        return self.parse(html)

    def parse(self, html: str) -> list[Product]:
        raise NotImplementedError
