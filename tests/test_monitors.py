import asyncio
import json
from pathlib import Path

import httpx

from pokegrab.monitors.amazon import AmazonMonitor, parse_amazon_payload
from pokegrab.monitors.base import BlockedPage
from pokegrab.monitors.bestbuy import BestBuyMonitor, parse_bestbuy_payload
from pokegrab.monitors.pokemoncenter import PokemonCenterMonitor
from pokegrab.monitors.target import TargetMonitor
from pokegrab.monitors.walmart import WalmartMonitor

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_bestbuy_payload_parses_stock():
    products = parse_bestbuy_payload(json.loads(load("bestbuy.json")))
    by_id = {product.id: product for product in products}
    assert by_id["6501234"].in_stock is True
    assert by_id["6501234"].price == 49.99
    assert by_id["6505678"].in_stock is False


def test_bestbuy_search_keeps_and_operator_in_the_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=json.loads(load("bestbuy.json")))

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            monitor = BestBuyMonitor("test-key", pause_seconds=0)
            return await monitor.search(client, ["elite trainer box"])

    products = asyncio.run(scenario())
    assert "search=elite&trainer&box" in seen["url"]
    assert "apiKey=test-key" in seen["url"]
    assert len(products) == 2


def test_amazon_payload_uses_buy_box_listing():
    products = parse_amazon_payload(json.loads(load("amazon.json")))
    by_id = {product.id: product for product in products}
    assert by_id["B0ETB12345"].in_stock is True
    assert by_id["B0ETB12345"].price == 49.99
    assert by_id["B0TIN12345"].in_stock is False


def test_amazon_search_reuses_access_token():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600})
        body = json.loads(request.content.decode())
        assert body["partnerTag"] == "tag-20"
        assert body["availability"] == "IncludeOutOfStock"
        assert request.headers["x-marketplace"] == "www.amazon.com"
        return httpx.Response(200, json=json.loads(load("amazon.json")))

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            monitor = AmazonMonitor("id", "secret", "tag-20", pause_seconds=0)
            return await monitor.search(client, ["elite trainer box", "tin"])

    products = asyncio.run(scenario())
    assert sum(url.endswith("/token") for url in calls) == 1
    assert len(products) == 2


def test_pokemon_center_html_cards():
    products = {product.id: product for product in PokemonCenterMonitor().parse(load("pokemoncenter.html"))}
    assert products["10-10023-101"].in_stock is True
    assert products["10-10023-101"].price == 49.99
    assert products["10-10023-101"].url.endswith("/pokemon-tcg-elite-trainer-box")
    assert products["10-20001-101"].in_stock is False


def test_pokemon_center_next_data():
    products = PokemonCenterMonitor().parse(load("pokemoncenter_next.json.html"))
    assert products[0].id == "10-10023-101"
    assert products[0].in_stock is True
    assert products[0].image.endswith("etb.png")


def test_target_next_data_and_html_cards():
    embedded = {product.id: product for product in TargetMonitor().parse(load("target.html"))}
    assert embedded["12345678"].in_stock is True
    assert embedded["12345678"].price == 49.99
    assert embedded["87654321"].in_stock is False
    cards = TargetMonitor().parse(load("target_cards.html"))
    assert cards[0].id == "12345678"
    assert cards[0].in_stock is True
    assert cards[0].price == 49.99


def test_walmart_next_data_and_html_cards():
    embedded = {product.id: product for product in WalmartMonitor().parse(load("walmart.html"))}
    assert embedded["111"].in_stock is True
    assert embedded["111"].price == 49.88
    assert embedded["111"].url.endswith("/111")
    assert embedded["222"].in_stock is False
    cards = WalmartMonitor().parse(load("walmart_cards.html"))
    assert cards[0].id == "111"
    assert cards[0].in_stock is True


def test_challenge_pages_are_skipped():
    html = load("blocked.html")
    for monitor in (PokemonCenterMonitor(), TargetMonitor(), WalmartMonitor()):
        try:
            monitor.parse(html)
        except BlockedPage:
            continue
        raise AssertionError(f"{monitor.name} parsed a challenge page")
