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
    r'href="(?:https://www\.pokemoncenter\.com)?(/product/([^/"#?]+)/[^"]*)"',
    re.IGNORECASE,
)
_PRODUCT_FIELDS = {"price", "available", "inStock", "availability", "image", "images", "slug"}


class PokemonCenterMonitor(PageMonitor):
    name = "pokemoncenter"
    url_template = "https://www.pokemoncenter.com/search?q={query}"

    def parse(self, html: str) -> list[Product]:
        if is_blocked(200, html):
            raise BlockedPage("Pokemon Center returned a challenge page")
        products = _from_next_data(html)
        products.extend(_from_html(html))
        return products


def _from_next_data(html: str) -> list[Product]:
    data = extract_next_data(html)
    if not data:
        return []
    products = []
    for obj in walk_dicts(data):
        sku = obj.get("sku") or obj.get("productCode")
        name = obj.get("name") or obj.get("productName")
        if not isinstance(sku, str) or not isinstance(name, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9-]{4,}", sku):
            continue
        if not _PRODUCT_FIELDS.intersection(obj):
            continue
        products.append(
            Product(
                store="Pokemon Center",
                id=sku,
                name=name,
                price=_price(obj),
                url=f"https://www.pokemoncenter.com/product/{sku}",
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
                store="Pokemon Center",
                id=match.group(2),
                name=name,
                price=price_from_window(after),
                url="https://www.pokemoncenter.com" + match.group(1),
                image=image_from_regions(before, after),
                in_stock=stock_from_window(after),
            )
        )
    return products


def _price(obj: dict) -> float | None:
    price = obj.get("price")
    if isinstance(price, dict):
        for key in ("amount", "value", "current"):
            parsed = parse_price(price.get(key))
            if parsed is not None:
                return parsed
        return parse_price(price.get("formatted") or price.get("display"))
    return parse_price(price)


def _image(obj: dict) -> str | None:
    image = obj.get("image") or obj.get("images")
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        url = image.get("url") or image.get("src")
        return url if isinstance(url, str) else None
    if isinstance(image, list) and image:
        return _image({"image": image[0]})
    return None


def _stock(obj: dict) -> bool | None:
    for key in ("inStock", "available"):
        if isinstance(obj.get(key), bool):
            return obj[key]
    availability = obj.get("availability")
    if isinstance(availability, str):
        return stock_from_status(availability)
    if isinstance(availability, dict):
        for key in ("status", "display", "value", "message"):
            if isinstance(availability.get(key), str):
                parsed = stock_from_status(availability[key])
                if parsed is not None:
                    return parsed
    return None
