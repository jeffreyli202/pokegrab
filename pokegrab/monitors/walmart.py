import re

from pokegrab.models import Product
from pokegrab.monitors.base import BlockedPage
from pokegrab.monitors.pages import (
    PageMonitor,
    extract_next_data,
    card_regions,
    image_from_regions,
    is_blocked,
    price_from_window,
    stock_from_window,
    text_from_anchor,
    walk_dicts,
)
from pokegrab.parsing import parse_price, stock_from_status

_PRODUCT_HREF = re.compile(
    r'href="(?:https://www\.walmart\.com)?(/ip/[^"]+/(\d+))"',
    re.IGNORECASE,
)


class WalmartMonitor(PageMonitor):
    name = "walmart"
    url_template = "https://www.walmart.com/search?q={query}"

    def parse(self, html: str) -> list[Product]:
        if is_blocked(200, html):
            raise BlockedPage("Walmart returned a challenge page")
        products = _from_next_data(html)
        products.extend(_from_html(html))
        return products


def _from_next_data(html: str) -> list[Product]:
    data = extract_next_data(html)
    if not data:
        return []
    products = []
    for obj in walk_dicts(data):
        item_id = obj.get("usItemId")
        name = obj.get("name")
        if not item_id or not isinstance(name, str):
            continue
        path = obj.get("canonicalUrl") if isinstance(obj.get("canonicalUrl"), str) else f"/ip/{item_id}"
        if path.startswith("http"):
            url = path
        else:
            url = "https://www.walmart.com" + (path if path.startswith("/") else f"/{path}")
        image = obj.get("image") if isinstance(obj.get("image"), str) else None
        products.append(
            Product(
                store="Walmart",
                id=str(item_id),
                name=name,
                price=_price(obj),
                url=url,
                image=image,
                in_stock=_stock(obj),
            )
        )
    return products


def _from_html(html: str) -> list[Product]:
    products = []
    for match, before, after in card_regions(html, list(_PRODUCT_HREF.finditer(html))):
        name = text_from_anchor(html, match.start())
        if not name:
            continue
        products.append(
            Product(
                store="Walmart",
                id=match.group(2),
                name=name,
                price=price_from_window(after),
                url="https://www.walmart.com" + match.group(1),
                image=image_from_regions(before, after),
                in_stock=stock_from_window(after),
            )
        )
    return products


def _price(obj: dict) -> float | None:
    price_info = obj.get("priceInfo")
    if not isinstance(price_info, dict):
        return None
    return parse_price(price_info.get("linePrice") or price_info.get("itemPrice"))


def _stock(obj: dict) -> bool | None:
    availability = obj.get("availabilityStatusV2") or obj.get("availabilityStatusDisplayValue")
    if isinstance(availability, str):
        return stock_from_status(availability)
    if isinstance(availability, dict):
        for key in ("display", "value"):
            if isinstance(availability.get(key), str):
                parsed = stock_from_status(availability[key])
                if parsed is not None:
                    return parsed
    return None
