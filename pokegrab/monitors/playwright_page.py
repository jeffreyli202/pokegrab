from urllib.parse import quote_plus

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import BlockedPage, Monitor, MonitorError
from pokegrab.monitors.pages import is_blocked


class PlaywrightPageMonitor(Monitor):
    """Page monitor that renders search results in Chromium for sites that build them with JavaScript."""

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
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError as exc:
            raise MonitorError("Playwright is not installed: run pip install playwright") from exc

        url = self.url_template.format(query=quote_plus(keyword))
        try:
            browser = await self._ensure_browser()
            page = await browser.new_page()
        except PlaywrightError as exc:
            raise MonitorError(f"browser failed to start: {_first_line(exc)}") from exc
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
        except PlaywrightError as exc:
            raise MonitorError(f"page load failed: {_first_line(exc)}") from exc
        finally:
            await page.close()
        status = response.status if response else 200
        if is_blocked(status, html):
            raise BlockedPage(f"blocked ({status})")
        if status >= 400:
            raise MonitorError(f"page request failed ({status})")
        return self.parse(html)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def parse(self, html: str) -> list[Product]:
        raise NotImplementedError


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
