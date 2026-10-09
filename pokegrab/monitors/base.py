import asyncio

import httpx

from pokegrab.models import Product, dedupe_products

USER_AGENT = "Pokegrab/0.1 (Pokemon card restock notifier)"


class MonitorError(Exception):
    """A store scan failed and must not update the baseline."""


class BlockedPage(MonitorError):
    """The store returned a block or challenge page."""


class Monitor:
    name: str
    pause_seconds: float = 1.0

    async def search(self, client: httpx.AsyncClient, keywords: list[str]) -> list[Product]:
        found: list[Product] = []
        for index, keyword in enumerate(keywords):
            found.extend(await self.search_keyword(client, keyword))
            if self.pause_seconds and index < len(keywords) - 1:
                await asyncio.sleep(self.pause_seconds)
        return dedupe_products(found)

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        raise NotImplementedError
