import re

_OUT_OF_STOCK = ("out of stock", "sold out", "unavailable", "not available")
_IN_STOCK = ("in stock", "in stock scarce", "pre order", "preorder", "add to cart", "available now")


def parse_price(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)", str(value).replace(",", ""))
    if not match:
        return None
    return float(match.group(1))


def stock_from_status(value: str) -> bool | None:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if any(phrase in normalized for phrase in _OUT_OF_STOCK):
        return False
    if normalized in {"in stock", "in stock scarce", "preorder", "pre order", "available", "leadtime", "lead time"}:
        return True
    if any(phrase in normalized for phrase in _IN_STOCK):
        return True
    return None
