import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

STORE_NAMES = ("bestbuy", "amazon", "pokemoncenter", "target", "walmart", "ebay")
MIN_POLL_SECONDS = 60


@dataclass(frozen=True)
class Settings:
    poll_seconds: int
    price_min: float | None
    price_max: float | None
    keywords: list[str]
    exclude: list[str]
    stores: dict[str, bool]
    database: str
    discord_webhook_url: str
    bestbuy_api_key: str
    amazon_credential_id: str
    amazon_credential_secret: str
    amazon_partner_tag: str
    amazon_credential_version: str
    ebay_client_id: str
    ebay_client_secret: str


def load_settings(path: Path | None = None, *, load_env: bool = True) -> Settings:
    if load_env:
        load_dotenv()
    config_path = path or _default_config_path()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} must be a mapping")

    keywords = _string_list(raw.get("keywords"), "keywords")
    if not keywords:
        raise ValueError("config keywords must include at least one phrase")

    stores = {name: True for name in STORE_NAMES}
    configured = raw.get("stores") or {}
    if not isinstance(configured, dict):
        raise ValueError("config stores must be a mapping")
    for name, enabled in configured.items():
        if name in stores:
            stores[name] = bool(enabled)

    poll_seconds = int(raw.get("poll_seconds", 180))
    if poll_seconds < MIN_POLL_SECONDS:
        poll_seconds = MIN_POLL_SECONDS

    return Settings(
        poll_seconds=poll_seconds,
        price_min=_optional_float(raw.get("price_min")),
        price_max=_optional_float(raw.get("price_max")),
        keywords=keywords,
        exclude=_string_list(raw.get("exclude"), "exclude"),
        stores=stores,
        database=str(raw.get("database") or "data/state.db"),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        bestbuy_api_key=os.environ.get("BESTBUY_API_KEY", "").strip(),
        amazon_credential_id=os.environ.get("AMAZON_CREDENTIAL_ID", "").strip(),
        amazon_credential_secret=os.environ.get("AMAZON_CREDENTIAL_SECRET", "").strip(),
        amazon_partner_tag=os.environ.get("AMAZON_PARTNER_TAG", "").strip(),
        amazon_credential_version=os.environ.get("AMAZON_CREDENTIAL_VERSION", "3.1").strip() or "3.1",
        ebay_client_id=os.environ.get("EBAY_CLIENT_ID", "").strip(),
        ebay_client_secret=os.environ.get("EBAY_CLIENT_SECRET", "").strip(),
    )


def _default_config_path() -> Path:
    override = os.environ.get("POKEGRAB_CONFIG", "").strip()
    if override:
        return Path(override)
    local = Path("config.yaml")
    if local.exists():
        return local
    return Path("config.example.yaml")


def _string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"config {label} must be a list of strings")
    return [item.strip() for item in value]


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
