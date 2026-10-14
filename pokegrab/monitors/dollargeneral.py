import asyncio
import json
import logging
from urllib.parse import quote_plus

import httpx

from pokegrab.match import name_matches
from pokegrab.models import Product, dedupe_products
from pokegrab.monitors.base import BlockedPage, MonitorError
from pokegrab.monitors.pages import is_blocked
from pokegrab.monitors.playwright_page import PlaywrightPageMonitor, _first_line
from pokegrab.parsing import parse_price

SEARCH_PAGE = "https://www.dollargeneral.com/product-search?q={query}&productSearchedMode=manual"
SEARCH_API = "/omni/api/v5/search/shoppinglist/product/Provider"
DEFAULT_INCLUDE = ["trading card", "tcg", "booster", "card pack", "tin"]

logger = logging.getLogger(__name__)


class DollarGeneralMonitor(PlaywrightPageMonitor):
    """Checks shelf counts at chosen Dollar General stores.

    The site picks a store from the visitor's IP address, so each search request
    the page sends is rewritten to ask about one configured store instead.
    """

    name = "dollargeneral"
    prefiltered = True

    def __init__(
        self,
        stores: dict[str, str],
        search: str = "pokemon",
        include: list[str] | None = None,
        pause_seconds: float = 3.0,
    ):
        super().__init__(pause_seconds=pause_seconds)
        self.stores = stores
        self.query = search
        self.include = include or DEFAULT_INCLUDE

    async def search(self, client: httpx.AsyncClient, keywords: list[str]) -> list[Product]:
        found: list[Product] = []
        for index, (number, label) in enumerate(self.stores.items()):
            payload = await self._store_results(number)
            products = parse_dollargeneral_payload(payload, number, label, self.include)
            in_stock = [p for p in products if p.in_stock]
            logger.info(
                "dollargeneral store %s (%s): %d card items, %d in stock%s",
                number,
                label,
                len(products),
                len(in_stock),
                "".join(f"; {p.name} x{p.quantity}" for p in in_stock),
            )
            found.extend(products)
            if self.pause_seconds and index < len(self.stores) - 1:
                await asyncio.sleep(self.pause_seconds)
        return dedupe_products(found)

    async def _store_results(self, store_number: str) -> dict:
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError as exc:
            raise MonitorError("Playwright is not installed: run pip install playwright") from exc

        try:
            browser = await self._ensure_browser()
            page = await browser.new_page()
        except PlaywrightError as exc:
            raise MonitorError(f"browser failed to start: {_first_line(exc)}") from exc

        async def ask_for_store(route):
            try:
                body = json.loads(route.request.post_data or "{}")
            except ValueError:
                await route.continue_()
                return
            body["StoreNbr"] = int(store_number)
            body.setdefault("Filters", {})["inStock"] = False
            await route.continue_(post_data=json.dumps(body))

        results: asyncio.Queue = asyncio.Queue()

        async def keep_results(response):
            if SEARCH_API in response.url and response.request.method == "POST":
                try:
                    await results.put((response.status, await response.text()))
                except PlaywrightError:
                    await results.put((response.status, ""))

        page.on("response", keep_results)
        try:
            await page.route(f"**{SEARCH_API}*", ask_for_store)
            response = await page.goto(
                SEARCH_PAGE.format(query=quote_plus(self.query)), wait_until="domcontentloaded", timeout=30_000
            )
            status = response.status if response else 200
            if is_blocked(status, await page.content()):
                raise BlockedPage(f"blocked ({status})")
            api_status, text = await asyncio.wait_for(results.get(), timeout=30)
        except PlaywrightError as exc:
            raise MonitorError(f"store {store_number} search did not load: {_first_line(exc)}") from exc
        except asyncio.TimeoutError as exc:
            raise MonitorError(f"store {store_number} search never returned results") from exc
        finally:
            await page.close()
        if api_status >= 400:
            raise MonitorError(f"store {store_number} search failed ({api_status})")
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise MonitorError(f"store {store_number} search returned unreadable data ({api_status})") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
            raise MonitorError(f"store {store_number} search returned no item list")
        return payload


def parse_dollargeneral_payload(
    payload: dict, store_number: str, store_label: str, include: list[str] | None = None
) -> list[Product]:
    include = include or DEFAULT_INCLUDE
    products = []
    for item in payload.get("Items") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("Description")
        sku = item.get("sku") or item.get("UPC")
        if not isinstance(name, str) or not sku:
            continue
        if not name_matches(name, ["pokemon"], []) or not name_matches(name, include, []):
            continue
        quantity = item.get("AvailableStockStore")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            quantity = None
        image = item.get("Image")
        products.append(
            Product(
                store=f"Dollar General · {store_label}",
                id=f"{store_number}:{sku}",
                name=name,
                price=parse_price(item.get("Price")),
                url=SEARCH_PAGE.format(query=quote_plus(name)),
                image=image if isinstance(image, str) else None,
                in_stock=None if quantity is None else quantity > 0,
                quantity=None if quantity is None else int(quantity),
            )
        )
    return products
