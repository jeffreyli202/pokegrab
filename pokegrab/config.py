import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

STORE_NAMES = ("bestbuy", "amazon", "pokemoncenter", "target", "walmart", "ebay")
MIN_POLL_SECONDS = 60


@dataclass(frozen=True)
class EditionRule:
    """Prices for a non-English print run, picked when its words appear in a title."""

    words: list[str]
    msrp: dict[str, float]
    max_markup_percent: float


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
    alert_cooldown_hours: float = 6.0
    ebay_max_markup_percent: float = 15.0
    ebay_min_percent_of_msrp: float = 60.0
    ebay_msrp: dict[str, float] = field(default_factory=dict)
    ebay_exclude: list[str] = field(default_factory=list)
    ebay_editions: dict[str, EditionRule] = field(default_factory=dict)
    ebay_extra_searches: list[str] = field(default_factory=list)
    store_poll_seconds: dict[str, int] = field(default_factory=dict)

    def poll_seconds_for(self, store: str) -> int:
        return self.store_poll_seconds.get(store, self.poll_seconds)


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

    poll_seconds = max(int(raw.get("poll_seconds", 180)), MIN_POLL_SECONDS)
    store_poll_seconds = _store_poll_seconds(raw.get("store_poll_seconds"))

    cooldown = float(raw.get("alert_cooldown_hours", 6))
    if cooldown < 0:
        raise ValueError("config alert_cooldown_hours cannot be negative")

    ebay = raw.get("ebay") or {}
    if not isinstance(ebay, dict):
        raise ValueError("config ebay must be a mapping")
    markup = float(ebay.get("max_markup_percent", 15))
    if markup < 0:
        raise ValueError("config ebay.max_markup_percent cannot be negative")
    floor = float(ebay.get("min_percent_of_msrp", 60))
    if not 0 <= floor <= 100:
        raise ValueError("config ebay.min_percent_of_msrp must be between 0 and 100")

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
        alert_cooldown_hours=cooldown,
        ebay_max_markup_percent=markup,
        ebay_min_percent_of_msrp=floor,
        ebay_msrp=_price_table(ebay.get("msrp"), "ebay.msrp"),
        ebay_exclude=_string_list(ebay.get("exclude"), "ebay.exclude"),
        ebay_editions=_editions(ebay.get("editions"), markup),
        ebay_extra_searches=_string_list(ebay.get("extra_searches"), "ebay.extra_searches"),
        store_poll_seconds=store_poll_seconds,
    )


def _store_poll_seconds(value: object) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("config store_poll_seconds must map store names to seconds")
    overrides = {}
    for name, seconds in value.items():
        if name not in STORE_NAMES:
            raise ValueError(f"config store_poll_seconds has unknown store {name!r}")
        overrides[name] = max(int(seconds), MIN_POLL_SECONDS)
    return overrides


def _editions(value: object, default_markup: float) -> dict[str, EditionRule]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("config ebay.editions must be a mapping")
    editions = {}
    for name, rule in value.items():
        label = f"ebay.editions.{name}"
        if not isinstance(rule, dict):
            raise ValueError(f"config {label} must be a mapping")
        words = _string_list(rule.get("words"), f"{label}.words")
        if not words:
            raise ValueError(f"config {label}.words must list at least one word")
        markup = float(rule.get("max_markup_percent", default_markup))
        if markup < 0:
            raise ValueError(f"config {label}.max_markup_percent cannot be negative")
        editions[str(name)] = EditionRule(
            words=words,
            msrp=_price_table(rule.get("msrp"), f"{label}.msrp"),
            max_markup_percent=markup,
        )
    return editions


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


def _price_table(value: object, label: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config {label} must map product names to prices")
    table = {}
    for name, price in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"config {label} has an empty product name")
        amount = float(price)
        if amount <= 0:
            raise ValueError(f"config {label} price for {name!r} must be above zero")
        table[name.strip()] = amount
    return table


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
