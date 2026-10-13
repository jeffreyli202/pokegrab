import asyncio
import logging
from datetime import datetime, timezone

import httpx

from pokegrab.models import Product

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 30.0


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def notify(self, client: httpx.AsyncClient, message: str) -> None:
        if not self.webhook_url:
            return
        await self._post(client, {"content": message})

    async def send(self, client: httpx.AsyncClient, product: Product) -> None:
        if not self.webhook_url:
            logger.warning("Discord webhook is not set; restock for %s was not posted", product.name)
            return
        await self._post(client, payload_for(product))

    async def _post(self, client: httpx.AsyncClient, payload: dict) -> None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = await client.post(self.webhook_url, json=payload)
            if response.status_code != 429 or attempt == MAX_ATTEMPTS:
                break
            wait = _retry_after(response)
            logger.info("Discord rate limit hit; waiting %.1fs", wait)
            await asyncio.sleep(wait)
        if response.status_code >= 400:
            raise RuntimeError(f"Discord webhook returned {response.status_code}")


def _retry_after(response: httpx.Response) -> float:
    wait = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            wait = float(payload.get("retry_after"))
    except (ValueError, TypeError):
        wait = None
    if wait is None:
        try:
            wait = float(response.headers.get("Retry-After", 1))
        except ValueError:
            wait = 1.0
    return min(max(wait, 0.5), MAX_RETRY_WAIT_SECONDS)


def payload_for(product: Product) -> dict:
    price = f"${product.price:.2f}" if product.price is not None else "Price unavailable"
    description = f"**{product.store}** · {price}"
    if product.msrp is not None and product.total is not None:
        description = "\n".join(
            [
                f"**{product.store}** · {_price_with_shipping(product)}",
                f"{_msrp_label(product)} ${product.msrp:.2f} · {_markup_text(product.total, product.msrp)}",
            ]
        )
    embed = {
        "title": product.name[:256],
        "url": product.url,
        "description": description,
        "color": 0xE3350D,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if product.image:
        embed["thumbnail"] = {"url": product.image}
    return {"embeds": [embed]}


def _price_with_shipping(product: Product) -> str:
    if product.shipping is None:
        return f"${product.price:.2f} (shipping not listed)"
    if product.shipping == 0:
        return f"${product.price:.2f} with free shipping"
    return f"${product.price:.2f} + ${product.shipping:.2f} shipping = **${product.total:.2f}**"


def _msrp_label(product: Product) -> str:
    if product.edition:
        return f"{product.edition.title()} MSRP"
    return "MSRP"


def _markup_text(total: float, msrp: float) -> str:
    difference = round(total - msrp, 2)
    percent = difference / msrp * 100
    if abs(difference) < 0.01:
        return "**at MSRP**"
    if difference > 0:
        return f"**+${difference:.2f} (+{percent:.1f}%) over MSRP**"
    return f"**${-difference:.2f} ({-percent:.1f}%) under MSRP**"
