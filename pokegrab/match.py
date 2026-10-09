import re


def name_matches(name: str, keywords: list[str], exclude: list[str]) -> bool:
    if not any(_contains(name, keyword) for keyword in keywords):
        return False
    return not any(_contains(name, term) for term in exclude)


def price_in_range(price: float | None, price_min: float | None, price_max: float | None) -> bool:
    if price is None:
        return True
    if price_min is not None and price < price_min:
        return False
    if price_max is not None and price > price_max:
        return False
    return True


def _contains(text: str, term: str) -> bool:
    parts = term.casefold().split()
    if not parts:
        return False
    pattern = r"\b" + r"\s+".join(re.escape(part) for part in parts) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None
