import base64
import math
import time

import httpx

from pokegrab.config import EditionRule
from pokegrab.match import msrp_for, name_matches
from pokegrab.models import Product
from pokegrab.monitors.base import Monitor, MonitorError
from pokegrab.parsing import parse_price

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayMonitor(Monitor):
    name = "ebay"
    # Listings already up when the bot starts are still deals worth posting.
    baseline_first_scan = False
    dedupe_by_title = True

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        msrp: dict[str, float],
        max_markup_percent: float = 15.0,
        exclude: list[str] | None = None,
        pause_seconds: float = 1.0,
        min_percent_of_msrp: float = 60.0,
        editions: dict[str, EditionRule] | None = None,
        extra_searches: list[str] | None = None,
    ):
        if not msrp:
            raise ValueError("eBay needs an msrp table in config to judge prices")
        self.client_id = client_id
        self.client_secret = client_secret
        self.msrp = msrp
        self.max_markup_percent = max_markup_percent
        self.min_percent_of_msrp = min_percent_of_msrp
        self.exclude = exclude or []
        self.editions = editions or {}
        self.extra_searches = extra_searches or []
        self.pause_seconds = pause_seconds
        self._token = ""
        self._token_deadline = 0.0

    async def search(self, client: httpx.AsyncClient, keywords: list[str]) -> list[Product]:
        terms = list(dict.fromkeys([*keywords, *self.extra_searches]))
        return await super().search(client, terms)

    def markup_for(self, product: Product) -> float:
        if product.edition in self.editions:
            return self.editions[product.edition].max_markup_percent
        return self.max_markup_percent

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        token = await self._access_token(client)
        query = keyword if name_matches(keyword, ["pokemon"], []) else f"pokemon {keyword}"
        filters = ",".join(
            [
                f"price:[0..{self._search_ceiling()}]",
                "priceCurrency:USD",
                "buyingOptions:{FIXED_PRICE}",
                "conditions:{NEW}",
                "deliveryCountry:US",
            ]
        )
        response = await client.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params={
                "q": query,
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
        return [
            product
            for product in parse_ebay_payload(payload, self.msrp, self.exclude, self.editions)
            if within_price_band(product, self.markup_for(product), self.min_percent_of_msrp)
        ]

    def _search_ceiling(self) -> int:
        ceilings = [max(self.msrp.values()) * (1 + self.max_markup_percent / 100)]
        for rule in self.editions.values():
            if rule.msrp:
                ceilings.append(max(rule.msrp.values()) * (1 + rule.max_markup_percent / 100))
        return math.ceil(max(ceilings))

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
            raise MonitorError(f"eBay token request failed ({response.status_code}){_oauth_reason(response)}")
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise MonitorError("eBay token response did not include an access token")
        expires_in = int(payload.get("expires_in", 7200))
        self._token = token
        self._token_deadline = time.monotonic() + max(30, expires_in - 60)
        return token


def _oauth_reason(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    reason = " ".join(str(payload[key]) for key in ("error", "error_description") if isinstance(payload.get(key), str))
    return f": {reason}" if reason else ""


def within_price_band(product: Product, max_markup_percent: float, min_percent_of_msrp: float) -> bool:
    # Far below MSRP is almost always a single accessory (dice, playmat,
    # sleeves) whose title names the full box it came from.
    if product.msrp is None or product.total is None:
        return False
    floor = product.msrp * min_percent_of_msrp / 100
    ceiling = product.msrp * (1 + max_markup_percent / 100)
    return floor <= product.total <= ceiling


def edition_for(title: str, editions: dict[str, EditionRule]) -> str | None:
    for name, rule in editions.items():
        if name_matches(title, rule.words, []):
            return name
    return None


def parse_ebay_payload(
    payload: dict,
    msrp: dict[str, float],
    exclude: list[str] | None = None,
    editions: dict[str, EditionRule] | None = None,
) -> list[Product]:
    editions = editions or {}
    products = []
    for item in payload.get("itemSummaries") or []:
        item_id = item.get("itemId")
        title = item.get("title")
        url = item.get("itemWebUrl")
        if not item_id or not isinstance(title, str) or not url:
            continue
        if not name_matches(title, ["pokemon"], exclude or []):
            continue
        edition = edition_for(title, editions)
        # A foreign print is never priced against English MSRP; without its own
        # entry there is no fair price to compare to.
        table = editions[edition].msrp if edition else msrp
        original = msrp_for(title, table)
        if original is None:
            continue
        image = (item.get("image") or {}).get("imageUrl")
        products.append(
            Product(
                store="eBay",
                id=str(item_id),
                name=title,
                price=parse_price((item.get("price") or {}).get("value")),
                url=str(url),
                image=image if isinstance(image, str) else None,
                in_stock=True,
                msrp=original,
                shipping=_cheapest_shipping(item.get("shippingOptions")),
                edition=edition,
            )
        )
    return products


def _cheapest_shipping(options: object) -> float | None:
    if not isinstance(options, list):
        return None
    costs = []
    for option in options:
        if not isinstance(option, dict):
            continue
        cost = parse_price((option.get("shippingCost") or {}).get("value"))
        if cost is not None:
            costs.append(cost)
    return min(costs) if costs else None
