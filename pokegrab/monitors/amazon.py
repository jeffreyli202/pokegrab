import time

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import Monitor, MonitorError
from pokegrab.parsing import parse_price, stock_from_status

TOKEN_ENDPOINTS = {
    "3.1": "https://api.amazon.com/auth/o2/token",
    "3.2": "https://api.amazon.co.uk/auth/o2/token",
    "3.3": "https://api.amazon.co.jp/auth/o2/token",
}
SEARCH_URL = "https://creatorsapi.amazon/catalog/v1/searchItems"
MARKETPLACE = "www.amazon.com"
RESOURCES = [
    "images.primary.medium",
    "itemInfo.title",
    "offersV2.listings.price",
    "offersV2.listings.availability",
    "offersV2.listings.isBuyBoxWinner",
]


class AmazonMonitor(Monitor):
    name = "amazon"

    def __init__(
        self,
        credential_id: str,
        credential_secret: str,
        partner_tag: str,
        credential_version: str = "3.1",
        pause_seconds: float = 1.0,
    ):
        try:
            self.token_url = TOKEN_ENDPOINTS[credential_version]
        except KeyError as exc:
            raise ValueError("AMAZON_CREDENTIAL_VERSION must be 3.1, 3.2, or 3.3") from exc
        self.credential_id = credential_id
        self.credential_secret = credential_secret
        self.partner_tag = partner_tag
        self.pause_seconds = pause_seconds
        self._token = ""
        self._token_deadline = 0.0

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        token = await self._access_token(client)
        response = await client.post(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-marketplace": MARKETPLACE,
            },
            json={
                "keywords": keyword,
                "partnerTag": self.partner_tag,
                "marketplace": MARKETPLACE,
                "itemCount": 10,
                "availability": "IncludeOutOfStock",
                "resources": RESOURCES,
            },
        )
        if response.status_code >= 400:
            raise MonitorError(f"Amazon request failed ({response.status_code})")
        payload = response.json()
        if not isinstance(payload, dict):
            raise MonitorError("Amazon returned an unexpected response")
        if payload.get("errors") and not (payload.get("searchResult") or {}).get("items"):
            raise MonitorError("Amazon returned an error response")
        return parse_amazon_payload(payload)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._token_deadline:
            return self._token
        response = await client.post(
            self.token_url,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "client_id": self.credential_id,
                "client_secret": self.credential_secret,
                "scope": "creatorsapi::default",
            },
        )
        if response.status_code >= 400:
            raise MonitorError(f"Amazon token request failed ({response.status_code})")
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise MonitorError("Amazon token response did not include an access token")
        expires_in = 3600
        if isinstance(payload.get("expires_in"), int):
            expires_in = payload["expires_in"]
        self._token = token
        self._token_deadline = time.monotonic() + max(30, expires_in - 60)
        return token


def parse_amazon_payload(payload: dict) -> list[Product]:
    products = []
    items = (payload.get("searchResult") or {}).get("items") or []
    for item in items:
        asin = item.get("asin")
        title = ((item.get("itemInfo") or {}).get("title") or {}).get("displayValue")
        if not asin or not title:
            continue
        listing = _featured_listing((item.get("offersV2") or {}).get("listings") or [])
        availability = (listing or {}).get("availability") or {}
        status = availability.get("type") if isinstance(availability, dict) else None
        price = None
        if listing:
            money = (listing.get("price") or {}).get("money") or {}
            price = parse_price(money.get("amount"))
        image = (((item.get("images") or {}).get("primary") or {}).get("medium") or {}).get("url")
        url = item.get("detailPageURL") or f"https://www.amazon.com/dp/{asin}"
        products.append(
            Product(
                store="Amazon",
                id=str(asin),
                name=str(title),
                price=price,
                url=str(url),
                image=image if isinstance(image, str) else None,
                in_stock=stock_from_status(str(status)) if isinstance(status, str) else None,
            )
        )
    return products


def _featured_listing(listings: list[dict]) -> dict | None:
    if not listings:
        return None
    for listing in listings:
        if listing.get("isBuyBoxWinner"):
            return listing
    return listings[0]
