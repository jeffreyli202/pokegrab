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


def test_missing_webhook_does_not_post():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("webhook was called")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await DiscordNotifier("").send(client, product())

    asyncio.run(scenario())
