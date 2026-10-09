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
    r'href="(?:https://www\.target\.com)?(/p/[^"]*?/-/A-(\d+))"',
    re.IGNORECASE,
)


class TargetMonitor(PageMonitor):
    name = "target"
    url_template = "https://www.target.com/s?searchTerm={query}"

    def parse(self, html: str) -> list[Product]:
        if is_blocked(200, html):
            raise BlockedPage("Target returned a challenge page")
        products = _from_next_data(html)
        products.extend(_from_html(html))
        return products


def _from_next_data(html: str) -> list[Product]:
    data = extract_next_data(html)
    if not data:
        return []
    products = []
    for obj in walk_dicts(data):
        tcin = obj.get("tcin")
        name = _title(obj)
        if not tcin or not name:
            continue
        products.append(
            Product(
                store="Target",
                id=str(tcin),
                name=name,
                price=_price(obj),
                url=f"https://www.target.com/p/-/A-{tcin}",
                image=_image(obj),
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
                store="Target",
                id=match.group(2),
                name=name,
                price=price_from_window(after),
                url="https://www.target.com" + match.group(1),
                image=image_from_regions(before, after),
                in_stock=stock_from_window(after),
            )
        )
    return products


def _title(obj: dict) -> str | None:
    item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
    description = item.get("product_description") or item.get("productDescription") or {}
    if isinstance(description, dict) and isinstance(description.get("title"), str):
        return description["title"]
    for key in ("title", "name"):
        if isinstance(obj.get(key), str):
            return obj[key]
    return None


def _price(obj: dict) -> float | None:
    item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    for key in ("current_retail", "currentRetail", "formatted_current_price", "formattedCurrentPrice"):
        parsed = parse_price(price.get(key))
        if parsed is not None:
            return parsed
    return None


def _image(obj: dict) -> str | None:
    item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
    enrichment = item.get("enrichment") if isinstance(item.get("enrichment"), dict) else {}
    images = enrichment.get("images") if isinstance(enrichment.get("images"), dict) else {}
    url = images.get("primary_image_url") or images.get("primaryImageUrl")
    return url if isinstance(url, str) else None


def _stock(obj: dict) -> bool | None:
    availability = obj.get("availability")
    if not isinstance(availability, dict):
        return None
    network = availability.get("available_to_promise_network") or availability.get("availableToPromiseNetwork")
    source = network if isinstance(network, dict) else availability
    status = source.get("availability_status") or source.get("availabilityStatus")
    if not isinstance(status, str):
        return None
    return stock_from_status(status)
