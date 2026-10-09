from urllib.parse import quote

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import Monitor, MonitorError
from pokegrab.parsing import parse_price

SHOW_FIELDS = "sku,name,salePrice,url,image,onlineAvailability"


class BestBuyMonitor(Monitor):
    name = "bestbuy"

    def __init__(self, api_key: str, pause_seconds: float = 1.0):
        self.api_key = api_key
        self.pause_seconds = pause_seconds

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        term = "&".join(quote(part, safe="") for part in keyword.split())
        # The & inside the product filter is Best Buy's AND operator, so it has to
        # stay in the path instead of being parsed as a query separator.
        url = httpx.URL(
            "https://api.bestbuy.com/v1/products",
            params={
                "format": "json",
                "show": SHOW_FIELDS,
                "pageSize": 25,
                "apiKey": self.api_key,
            },
        )
        request_url = httpx.URL(
            scheme=url.scheme,
            host=url.host,
            raw_path=f"/v1/products(search={term})".encode() + b"?" + url.query,
        )
        response = await client.get(request_url)
        if response.status_code >= 400:
            raise MonitorError(f"Best Buy request failed ({response.status_code})")
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise MonitorError("Best Buy returned an error response")
        return parse_bestbuy_payload(payload)


def parse_bestbuy_payload(payload: dict) -> list[Product]:
    products = []
    for item in payload.get("products") or []:
        sku = item.get("sku")
        name = item.get("name")
        url = item.get("url")
        if sku is None or not name or not url:
            continue
        availability = item.get("onlineAvailability")
        in_stock = availability if isinstance(availability, bool) else None
        products.append(
            Product(
                store="Best Buy",
                id=str(sku),
                name=str(name),
                price=parse_price(item.get("salePrice")),
                url=str(url),
                image=item.get("image") if isinstance(item.get("image"), str) else None,
                in_stock=in_stock,
            )
        )
    return products
