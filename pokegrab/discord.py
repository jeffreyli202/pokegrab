import logging
from datetime import datetime, timezone

import httpx

from pokegrab.models import Product

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def notify(self, client: httpx.AsyncClient, message: str) -> None:
        if not self.webhook_url:
            return
        response = await client.post(self.webhook_url, json={"content": message})
        if response.status_code >= 400:
            raise RuntimeError(f"Discord webhook returned {response.status_code}")

    async def send(self, client: httpx.AsyncClient, product: Product) -> None:
        if not self.webhook_url:
            logger.warning("Discord webhook is not set; restock for %s was not posted", product.name)
            return
        response = await client.post(self.webhook_url, json=payload_for(product))
        if response.status_code >= 400:
            raise RuntimeError(f"Discord webhook returned {response.status_code}")


def payload_for(product: Product) -> dict:
    price = f"${product.price:.2f}" if product.price is not None else "Price unavailable"
    embed = {
        "title": product.name[:256],
        "url": product.url,
        "description": f"**{product.store}** · {price}",
        "color": 0xE3350D,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if product.image:
        embed["thumbnail"] = {"url": product.image}
    return {"embeds": [embed]}
