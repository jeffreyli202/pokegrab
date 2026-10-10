import asyncio
import logging

import httpx

from pokegrab.config import Settings, load_settings
from pokegrab.discord import DiscordNotifier
from pokegrab.monitors.amazon import AmazonMonitor
from pokegrab.monitors.base import USER_AGENT, Monitor, MonitorError
from pokegrab.monitors.bestbuy import BestBuyMonitor
from pokegrab.monitors.pokemoncenter import PokemonCenterMonitor
from pokegrab.monitors.target import TargetMonitor
from pokegrab.monitors.walmart import WalmartMonitor
from pokegrab.state import StockState

logger = logging.getLogger(__name__)


def build_monitors(settings: Settings) -> list[Monitor]:
    monitors: list[Monitor] = []
    if settings.stores.get("bestbuy"):
        if settings.bestbuy_api_key:
            monitors.append(BestBuyMonitor(settings.bestbuy_api_key))
        else:
            logger.warning("Best Buy skipped: set BESTBUY_API_KEY")
    if settings.stores.get("amazon"):
        if _amazon_ready(settings):
            monitors.append(
                AmazonMonitor(
                    settings.amazon_credential_id,
                    settings.amazon_credential_secret,
                    settings.amazon_partner_tag,
                    settings.amazon_credential_version,
                )
            )
        else:
            logger.warning("Amazon skipped: set AMAZON_CREDENTIAL_ID, AMAZON_CREDENTIAL_SECRET, and AMAZON_PARTNER_TAG")
    if settings.stores.get("pokemoncenter"):
        monitors.append(PokemonCenterMonitor())
    if settings.stores.get("target"):
        monitors.append(TargetMonitor())
    if settings.stores.get("walmart"):
        monitors.append(WalmartMonitor())
    return monitors


def _amazon_ready(settings: Settings) -> bool:
    return bool(settings.amazon_credential_id and settings.amazon_credential_secret and settings.amazon_partner_tag)


async def handle_scan(
    monitor: Monitor,
    client: httpx.AsyncClient,
    state: StockState,
    settings: Settings,
    notifier: DiscordNotifier,
) -> None:
    try:
        products = await monitor.search(client, settings.keywords)
    except MonitorError as exc:
        logger.warning("%s skipped this cycle: %s", monitor.name, exc)
        return
    except Exception:
        logger.exception("%s scan failed", monitor.name)
        return

    logger.info("%s scan found %d products", monitor.name, len(products))
    alerts = state.observe(monitor.name, products, settings)
    for product in alerts:
        logger.info("restock at %s: %s", product.store, product.name)
        try:
            await notifier.send(client, product)
        except Exception:
            logger.exception("Discord notify failed for %s", product.name)


async def _poll_forever(
    monitor: Monitor,
    client: httpx.AsyncClient,
    state: StockState,
    settings: Settings,
    notifier: DiscordNotifier,
) -> None:
    while True:
        await handle_scan(monitor, client, state, settings, notifier)
        await asyncio.sleep(settings.poll_seconds)


async def run(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    state = StockState(settings.database)
    notifier = DiscordNotifier(settings.discord_webhook_url)
    monitors = build_monitors(settings)
    if not monitors:
        raise SystemExit("No stores are enabled.")
    if not settings.discord_webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL is empty; scans will run but alerts will not post")
    store_list = ", ".join(m.name for m in monitors)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"},
        follow_redirects=True,
    ) as client:
        await notifier.notify(client, f"👋 Pokegrab is online! Monitoring: {store_list}!")
        try:
            await asyncio.gather(*(_poll_forever(monitor, client, state, settings, notifier) for monitor in monitors))
        finally:
            await notifier.notify(client, "🔴 Pokegrab is going offline.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("stopped")
