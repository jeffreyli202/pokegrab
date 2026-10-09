import json
import re
from html import unescape
from urllib.parse import quote_plus

import httpx

from pokegrab.models import Product
from pokegrab.monitors.base import BlockedPage, Monitor, MonitorError
from pokegrab.parsing import parse_price, stock_from_status

# Challenge pages are short. A normal catalog page that happens to mention one
# of these phrases in passing is left alone.
_MARKERS = (
    "robot or human",
    "are you a human",
    "please verify you are a human",
    "verify you are human",
    "px-captcha",
    "cf-challenge",
    "challenge-platform",
    "pardon our interruption",
    "unusual traffic",
    "access denied",
    "enable javascript and cookies to continue",
)


def is_blocked(status: int, body: str) -> bool:
    if status in {403, 429, 503}:
        return True
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body[:8000], re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).casefold() if title_match else ""
    sample = body[:5000].casefold()
    if any(marker in title for marker in _MARKERS):
        return True
    if len(body) < 20_000 and any(marker in sample for marker in _MARKERS):
        return True
    return False


async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    text = response.text
    if is_blocked(response.status_code, text):
        raise BlockedPage(f"blocked ({response.status_code})")
    if response.status_code >= 400:
        raise MonitorError(f"page request failed ({response.status_code})")
    return text


def extract_next_data(html: str) -> dict | None:
    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def walk_dicts(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_dicts(item)


def card_regions(html: str, matches: list[re.Match[str]]):
    """Text that belongs to one product link, stopping at the next link."""
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        after = html[match.end() : min(next_start, match.end() + 700)]
        before = html[max(0, match.start() - 300) : match.start()]
        yield match, before, after


def text_from_anchor(html: str, start: int) -> str:
    chunk = html[start : start + 500]
    match = re.search(r">\s*([^<]+?)\s*</a>", chunk, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def image_from_window(window: str) -> str | None:
    match = re.search(r'<img[^>]+src="([^"]+)"', window, re.IGNORECASE)
    if not match:
        return None
    return unescape(match.group(1))


def image_from_regions(before: str, after: str) -> str | None:
    return image_from_window(after) or image_from_window(before)


def price_from_window(window: str) -> float | None:
    match = re.search(r"\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)", window)
    if not match:
        return None
    return parse_price(match.group(0))


def stock_from_window(window: str) -> bool | None:
    return stock_from_status(unescape(re.sub(r"<[^>]+>", " ", window)))


class PageMonitor(Monitor):
    url_template: str

    def __init__(self, pause_seconds: float = 1.0):
        self.pause_seconds = pause_seconds

    async def search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[Product]:
        url = self.url_template.format(query=quote_plus(keyword))
        html = await fetch_html(client, url)
        return self.parse(html)

    def parse(self, html: str) -> list[Product]:
        raise NotImplementedError
