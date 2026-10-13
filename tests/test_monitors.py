import asyncio
import json
from pathlib import Path

import httpx

from pokegrab.config import EditionRule
from pokegrab.monitors.amazon import AmazonMonitor, parse_amazon_payload
from pokegrab.monitors.base import BlockedPage, MonitorError
from pokegrab.monitors.bestbuy import BestBuyMonitor, parse_bestbuy_payload
from pokegrab.monitors.ebay import EbayMonitor, parse_ebay_payload
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


EBAY_MSRP = {
    "pokemon center elite trainer box": 59.99,
    "elite trainer box": 49.99,
    "booster bundle": 26.94,
    "mini tin": 9.99,
    "tin": 26.99,
}
EBAY_EXCLUDE = ["empty", "playmat"]


def test_ebay_payload_attaches_msrp_and_cheapest_shipping():
    products = parse_ebay_payload(json.loads(load("ebay.json")), EBAY_MSRP, ["empty"])
    by_id = {p.id: p for p in products}
    assert by_id["v1|100|0"].msrp == 49.99
    assert by_id["v1|100|0"].shipping == 0
    assert by_id["v1|200|0"].msrp == 26.94
    assert by_id["v1|200|0"].shipping == 4.00
    assert by_id["v1|200|0"].total == 28.99
    assert by_id["v1|300|0"].msrp == 59.99
    assert by_id["v1|300|0"].shipping is None
    assert by_id["v1|800|0"].msrp == 9.99


def test_ebay_payload_drops_non_pokemon_excluded_and_unknown_types():
    ids = {p.id for p in parse_ebay_payload(json.loads(load("ebay.json")), EBAY_MSRP, ["empty"])}
    assert "v1|500|0" not in ids
    assert "v1|600|0" not in ids
    assert "v1|700|0" not in ids


def test_ebay_search_keeps_listings_near_msrp():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=json.loads(load("ebay.json")))

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            monitor = EbayMonitor("id", "secret", EBAY_MSRP, 15, EBAY_EXCLUDE, pause_seconds=0)
            return await monitor.search(client, ["elite trainer box"])

    products = asyncio.run(scenario())
    ids = {p.id for p in products}
    # $49.99 ETB, $28.99 shipped bundle (+7.6%), $64.99 PC ETB (+8.3%), $10.99 mini tin (+10%).
    assert ids == {"v1|100|0", "v1|200|0", "v1|300|0", "v1|800|0"}
    assert seen["params"]["q"] == "pokemon elite trainer box"
    assert "price:[0..69]" in seen["params"]["filter"]
    assert "deliveryCountry:US" in seen["params"]["filter"]
    assert "newlyListed" in seen["url"]
    assert "FIXED_PRICE" in seen["url"]
    assert seen["auth"].startswith("Bearer tok")


def test_ebay_skips_accessories_by_word_and_by_price_floor():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(200, json=json.loads(load("ebay.json")))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor("id", "secret", EBAY_MSRP, 15, EBAY_EXCLUDE, pause_seconds=0)
            return await monitor.search(client, ["elite trainer box"])

    ids = {p.id for p in asyncio.run(scenario())}
    # The playmat is priced like a real box, so only the word filter catches it.
    assert "v1|900|0" not in ids
    # $9.99 shipped is 20% of an ETB's MSRP: the promo card, not the box.
    assert "v1|910|0" not in ids
    assert "v1|100|0" in ids


def test_ebay_price_floor_can_be_turned_off():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(200, json=json.loads(load("ebay.json")))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor("id", "secret", EBAY_MSRP, 15, ["empty"], pause_seconds=0, min_percent_of_msrp=0)
            return await monitor.search(client, ["elite trainer box"])

    assert "v1|910|0" in {p.id for p in asyncio.run(scenario())}


EDITIONS = {
    "japanese": EditionRule(
        words=["japanese", "jp"],
        msrp={"booster box": 37.93, "high class pack": 34.77},
        max_markup_percent=60,
    ),
    "korean": EditionRule(words=["korean"], msrp={"booster box": 22.49}, max_markup_percent=60),
}


def ebay_items(*items):
    return {
        "itemSummaries": [
            {
                "itemId": item_id,
                "title": title,
                "price": {"value": str(price)},
                "shippingOptions": [{"shippingCost": {"value": str(shipping)}}],
                "itemWebUrl": f"https://www.ebay.com/itm/{item_id}",
            }
            for item_id, title, price, shipping in items
        ]
    }


def test_asian_editions_use_their_own_msrp():
    payload = ebay_items(
        ("jp", "Pokemon Abyss Eye Booster Box Japanese Sealed", 45.00, 15.00),
        ("hc", "Pokemon MEGA Dream ex High Class Pack Box JP", 40.00, 0),
        ("kr", "Pokemon Korean Booster Box Sealed", 28.00, 5.00),
        ("en", "Pokemon Perfect Order Booster Box", 160.00, 0),
    )
    by_id = {p.id: p for p in parse_ebay_payload(payload, {"booster box": 161.64}, [], EDITIONS)}
    assert by_id["jp"].msrp == 37.93
    assert by_id["jp"].edition == "japanese"
    assert by_id["hc"].msrp == 34.77
    assert by_id["kr"].msrp == 22.49
    assert by_id["en"].msrp == 161.64
    assert by_id["en"].edition is None


def test_asian_listing_without_its_own_price_is_skipped():
    payload = ebay_items(("jp-etb", "Pokemon Japanese Elite Trainer Box", 45.00, 0))
    products = parse_ebay_payload(payload, {"elite trainer box": 49.99}, [], EDITIONS)
    assert products == []


def test_asian_edition_markup_is_applied_per_listing():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(
                200,
                json=ebay_items(
                    # 37.93 * 1.6 = 60.69, so $60 shipped fits and $62 does not.
                    ("jp-ok", "Pokemon Booster Box Japanese", 45.00, 15.00),
                    ("jp-high", "Pokemon Booster Box Japanese", 50.00, 12.00),
                    # English allows only 15%: 161.64 * 1.15 = 185.89.
                    ("en-high", "Pokemon Booster Box", 190.00, 0),
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor("id", "secret", {"booster box": 161.64}, 15, [], pause_seconds=0, editions=EDITIONS)
            return await monitor.search_keyword(client, "booster box")

    assert {p.id for p in asyncio.run(scenario())} == {"jp-ok"}


def test_ebay_extra_searches_are_added_once():
    queries = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok"})
        queries.append(request.url.params["q"])
        return httpx.Response(200, json={"itemSummaries": []})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor(
                "id",
                "secret",
                EBAY_MSRP,
                pause_seconds=0,
                extra_searches=["high class pack", "booster bundle"],
            )
            await monitor.search(client, ["booster bundle"])

    asyncio.run(scenario())
    assert queries == ["pokemon booster bundle", "pokemon high class pack"]


def test_ebay_token_failure_reports_ebay_reason():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": "invalid_client", "error_description": "client authentication failed"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor("id", "secret", EBAY_MSRP, pause_seconds=0)
            await monitor.search(client, ["elite trainer box"])

    try:
        asyncio.run(scenario())
    except MonitorError as exc:
        assert "invalid_client client authentication failed" in str(exc)
    else:
        raise AssertionError("token failure was not raised")


def test_ebay_zero_markup_only_keeps_msrp_or_below():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(200, json=json.loads(load("ebay.json")))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monitor = EbayMonitor("id", "secret", EBAY_MSRP, 0, EBAY_EXCLUDE, pause_seconds=0)
            return await monitor.search(client, ["pokemon elite trainer box"])

    assert {p.id for p in asyncio.run(scenario())} == {"v1|100|0"}
