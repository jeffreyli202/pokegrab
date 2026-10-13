import asyncio

import httpx

from pokegrab.discord import DiscordNotifier, payload_for
from pokegrab.models import Product


def product() -> Product:
    return Product(
        store="Best Buy",
        id="6501234",
        name="Pokemon TCG Elite Trainer Box",
        price=49.99,
        url="https://www.bestbuy.com/site/pokemon-elite-trainer-box/6501234.p",
        image="https://example.com/etb.jpg",
        in_stock=True,
    )


def test_payload_includes_store_price_and_link():
    payload = payload_for(product())
    embed = payload["embeds"][0]
    assert embed["title"] == "Pokemon TCG Elite Trainer Box"
    assert embed["url"].startswith("https://www.bestbuy.com/")
    assert "Best Buy" in embed["description"]
    assert "$49.99" in embed["description"]
    assert embed["thumbnail"]["url"] == "https://example.com/etb.jpg"


def ebay_product(price, shipping, msrp=49.99) -> Product:
    return Product(
        store="eBay",
        id="v1|1|0",
        name="Pokemon TCG Elite Trainer Box",
        price=price,
        url="https://www.ebay.com/itm/1",
        image=None,
        in_stock=True,
        msrp=msrp,
        shipping=shipping,
    )


def test_ebay_payload_shows_markup_over_msrp():
    description = payload_for(ebay_product(52.99, 2.00))["embeds"][0]["description"]
    assert "$52.99 + $2.00 shipping = **$54.99**" in description
    assert "MSRP $49.99" in description
    assert "+$5.00 (+10.0%) over MSRP" in description


def test_ebay_payload_names_the_edition_msrp():
    item = Product(
        store="eBay",
        id="v1|2|0",
        name="Pokemon Booster Box Japanese",
        price=45.00,
        url="https://www.ebay.com/itm/2",
        image=None,
        in_stock=True,
        msrp=37.93,
        shipping=15.00,
        edition="japanese",
    )
    description = payload_for(item)["embeds"][0]["description"]
    assert "Japanese MSRP $37.93" in description
    assert "+$22.07 (+58.2%) over MSRP" in description


def test_ebay_payload_shows_under_and_at_msrp():
    under = payload_for(ebay_product(44.99, 0))["embeds"][0]["description"]
    assert "with free shipping" in under
    assert "$5.00 (10.0%) under MSRP" in under
    at = payload_for(ebay_product(49.99, None))["embeds"][0]["description"]
    assert "shipping not listed" in at
    assert "at MSRP" in at


def test_send_posts_webhook():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(204)

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await DiscordNotifier("https://discord.example/webhook").send(client, product())

    asyncio.run(scenario())
    assert seen["url"] == "https://discord.example/webhook"
    assert b"Elite Trainer Box" in seen["body"]


def test_rate_limit_waits_and_retries(monkeypatch):
    calls = []
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("pokegrab.discord.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 1.5})
        return httpx.Response(204)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await DiscordNotifier("https://discord.example/webhook").send(client, product())

    asyncio.run(scenario())
    assert len(calls) == 2
    assert waits == [1.5]


def test_rate_limit_gives_up_after_three_tries(monkeypatch):
    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr("pokegrab.discord.asyncio.sleep", fake_sleep)

    async def scenario():
        transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"retry_after": 1}))
        async with httpx.AsyncClient(transport=transport) as client:
            await DiscordNotifier("https://discord.example/webhook").send(client, product())

    try:
        asyncio.run(scenario())
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("rate limit was not raised")


def test_missing_webhook_does_not_post():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("webhook was called")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await DiscordNotifier("").send(client, product())

    asyncio.run(scenario())
