import base64
import time

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import Monitor, MonitorError
from pokegrab.parsing import parse_price

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayMonitor(Monitor):
    name = "ebay"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        price_max: float | None = None,
        pause_seconds: float = 1.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.price_max = price_max
        self.pause_seconds = pause_seconds
        self._token = ""
        self._token_deadline = 0.0

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        token = await self._access_token(client)
        max_price = int(self.price_max or 500)
        filters = ",".join([
            f"price:[0..{max_price}]",
            "priceCurrency:USD",
            "buyingOptions:{FIXED_PRICE}",
            "conditions:{NEW}",
        ])
        response = await client.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params={
                "q": keyword,
                "filter": filters,
                "sort": "newlyListed",
                "limit": 50,
            },
        )
        if response.status_code >= 400:
            raise MonitorError(f"eBay request failed ({response.status_code})")
        payload = response.json()
        if not isinstance(payload, dict):
            raise MonitorError("eBay returned an unexpected response")
        return parse_ebay_payload(payload)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._token_deadline:
            return self._token
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=f"grant_type=client_credentials&scope={SCOPE}".encode(),
        )
        if response.status_code >= 400:
            raise MonitorError(f"eBay token request failed ({response.status_code})")
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise MonitorError("eBay token response did not include an access token")
        expires_in = int(payload.get("expires_in", 7200))
        self._token = token
        self._token_deadline = time.monotonic() + max(30, expires_in - 60)
        return token


def parse_ebay_payload(payload: dict) -> list[Product]:
    products = []
    for item in payload.get("itemSummaries") or []:
        item_id = item.get("itemId")
        title = item.get("title")
        url = item.get("itemWebUrl")
        if not item_id or not title or not url:
            continue
        price = parse_price((item.get("price") or {}).get("value"))
        image = (item.get("image") or {}).get("imageUrl")
        products.append(
            Product(
                store="eBay",
                id=str(item_id),
                name=str(title),
                price=price,
                url=str(url),
                image=image if isinstance(image, str) else None,
                in_stock=True,  # active listing = available
            )
        )
    return products
