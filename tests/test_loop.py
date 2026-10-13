import asyncio
import logging

import httpx

from pokegrab.config import Settings
from pokegrab.discord import DiscordNotifier
from pokegrab.main import build_monitors, handle_scan
from pokegrab.models import Product
from pokegrab.monitors.base import BlockedPage, Monitor
from pokegrab.state import StockState


def settings(tmp_path, **overrides) -> Settings:
    data = dict(
        poll_seconds=180,
        price_min=None,
        price_max=None,
        keywords=["elite trainer box"],
        exclude=[],
        stores={
            "bestbuy": True,
            "amazon": True,
            "pokemoncenter": False,
            "target": False,
            "walmart": False,
        },
        database=str(tmp_path / "state.db"),
        discord_webhook_url="https://discord.example/webhook",
        bestbuy_api_key="",
        amazon_credential_id="",
        amazon_credential_secret="",
        amazon_partner_tag="",
        amazon_credential_version="3.1",
        ebay_client_id="",
        ebay_client_secret="",
    )
    data.update(overrides)
    return Settings(**data)


class FakeMonitor(Monitor):
    name = "bestbuy"

    def __init__(self, products=None, error=None):
        self.products = products or []
        self.error = error
        self.pause_seconds = 0

    async def search(self, client, keywords):
        if self.error:
            raise self.error
        return self.products


def test_missing_api_keys_skip_those_stores(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    monitors = build_monitors(settings(tmp_path))
    assert monitors == []
    assert "BESTBUY_API_KEY" in caplog.text
    assert "AMAZON_PARTNER_TAG" in caplog.text


def test_blocked_scan_does_not_baseline(tmp_path):
    config = settings(tmp_path)
    state = StockState(config.database)
    monitor = FakeMonitor(error=BlockedPage("blocked (403)"))
    posted = []

    class Notifier(DiscordNotifier):
        async def send(self, client, product):
            posted.append(product)

    async def scenario():
        async with httpx.AsyncClient() as client:
            await handle_scan(monitor, client, state, config, Notifier(config.discord_webhook_url))
            monitor.error = None
            monitor.products = [
                Product("Best Buy", "1", "Pokemon TCG Elite Trainer Box", 49.99, "https://example.com/1", None, True)
            ]
            await handle_scan(monitor, client, state, config, Notifier(config.discord_webhook_url))

    asyncio.run(scenario())
    assert posted == []
    alerts = state.observe(
        "bestbuy",
        [Product("Best Buy", "2", "Pokemon TCG Elite Trainer Box", 54.99, "https://example.com/2", None, True)],
        config,
    )
    assert [item.id for item in alerts] == ["2"]
    state.close()


def test_scan_notifies_only_after_baseline(tmp_path):
    config = settings(tmp_path)
    state = StockState(config.database)
    item = Product("Best Buy", "1", "Pokemon TCG Elite Trainer Box", 49.99, "https://example.com/1", None, True)
    monitor = FakeMonitor([item])
    posted = []

    class Notifier(DiscordNotifier):
        async def send(self, client, product):
            posted.append(product.id)

    async def scenario():
        async with httpx.AsyncClient() as client:
            notifier = Notifier(config.discord_webhook_url)
            await handle_scan(monitor, client, state, config, notifier)
            await handle_scan(monitor, client, state, config, notifier)
            monitor.products = [
                item,
                Product("Best Buy", "2", "Pokemon TCG Elite Trainer Box", 54.99, "https://example.com/2", None, True),
            ]
            await handle_scan(monitor, client, state, config, notifier)

    asyncio.run(scenario())
    assert posted == ["2"]
    state.close()


def test_failed_discord_post_is_retried_next_scan(tmp_path):
    config = settings(tmp_path)
    state = StockState(config.database)
    monitor = FakeMonitor([])
    attempts = []

    class FlakyNotifier(DiscordNotifier):
        async def send(self, client, product):
            attempts.append(product.id)
            if len(attempts) == 1:
                raise RuntimeError("Discord webhook returned 429")

    async def scenario():
        async with httpx.AsyncClient() as client:
            notifier = FlakyNotifier(config.discord_webhook_url)
            await handle_scan(monitor, client, state, config, notifier)
            monitor.products = [
                Product("Best Buy", "1", "Pokemon TCG Elite Trainer Box", 49.99, "https://example.com/1", None, True)
            ]
            await handle_scan(monitor, client, state, config, notifier)
            await handle_scan(monitor, client, state, config, notifier)
            await handle_scan(monitor, client, state, config, notifier)

    asyncio.run(scenario())
    assert attempts == ["1", "1"]
    state.close()
