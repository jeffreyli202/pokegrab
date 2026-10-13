import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from pokegrab.config import Settings
from pokegrab.match import name_matches, price_in_range
from pokegrab.models import Product

# Words sellers pad titles with that do not change which product it is.
_FILLER = {
    "a", "and", "authentic", "brand", "english", "factory", "fast", "for", "free", "hand",
    "in", "new", "nib", "nisb", "of", "official", "pokemon", "sealed", "ship", "ships",
    "shipping", "tcg", "the", "us", "usa", "w", "with",
}


def title_fingerprint(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", name.casefold().replace("é", "e"))
    return " ".join(sorted({word for word in words if word not in _FILLER}))


def alert_keys(product: Product, dedupe_by_title: bool) -> list[str]:
    keys = [f"id:{product.id}"]
    if dedupe_by_title:
        keys.append(f"title:{title_fingerprint(product.name)}")
    return keys


class StockState:
    def __init__(self, path: str, clock: Callable[[], float] = time.time):
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._conn = sqlite3.connect(database)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                store TEXT NOT NULL,
                product_id TEXT NOT NULL,
                in_stock INTEGER NOT NULL,
                PRIMARY KEY (store, product_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS baselines (
                store TEXT PRIMARY KEY
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                store TEXT NOT NULL,
                alert_key TEXT NOT NULL,
                alerted_at REAL NOT NULL,
                PRIMARY KEY (store, alert_key)
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def observe(
        self,
        store: str,
        products: list[Product],
        settings: Settings,
        *,
        baseline: bool = True,
        dedupe_by_title: bool = False,
    ) -> list[Product]:
        """Return products worth posting. Call record_alert once each one is sent."""
        baselined = not baseline or self._is_baselined(store)
        cooldown_seconds = settings.alert_cooldown_hours * 3600
        claimed: set[str] = set()
        alerts: list[Product] = []
        for product in products:
            # A listing matched to an MSRP entry already names a known product type.
            if product.msrp is not None:
                if name_matches(product.name, settings.exclude, []):
                    continue
            elif not name_matches(product.name, settings.keywords, settings.exclude):
                continue
            previous = self._get(store, product.id)
            if not baselined:
                self._set(store, product.id, bool(product.in_stock))
                continue
            if product.in_stock is False:
                self._set(store, product.id, False)
                continue
            # A listing priced against MSRP has already passed a stricter check.
            in_range = product.msrp is not None or price_in_range(
                product.price, settings.price_min, settings.price_max
            )
            if product.in_stock is not True or not in_range or previous is True:
                continue
            keys = alert_keys(product, dedupe_by_title)
            if claimed.intersection(keys) or self._cooling_down(store, keys, cooldown_seconds):
                # The event is spent; only a later restock or new listing can alert.
                self._set(store, product.id, True)
                continue
            claimed.update(keys)
            alerts.append(product)
        if not baselined:
            self._mark_baselined(store)
        self._conn.commit()
        return alerts

    def record_alert(self, store: str, product: Product, *, dedupe_by_title: bool = False) -> None:
        now = self._clock()
        self._set(store, product.id, True)
        for key in alert_keys(product, dedupe_by_title):
            self._conn.execute(
                """
                INSERT INTO alerts (store, alert_key, alerted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(store, alert_key) DO UPDATE SET alerted_at = excluded.alerted_at
                """,
                (store, key, now),
            )
        self._conn.commit()

    def _cooling_down(self, store: str, keys: list[str], cooldown_seconds: float) -> bool:
        if cooldown_seconds <= 0:
            return False
        placeholders = ",".join("?" for _ in keys)
        row = self._conn.execute(
            f"SELECT MAX(alerted_at) FROM alerts WHERE store = ? AND alert_key IN ({placeholders})",
            (store, *keys),
        ).fetchone()
        last = row[0] if row else None
        return last is not None and self._clock() - last < cooldown_seconds

    def _is_baselined(self, store: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM baselines WHERE store = ?", (store,)).fetchone()
        return row is not None

    def _mark_baselined(self, store: str) -> None:
        self._conn.execute("INSERT OR IGNORE INTO baselines (store) VALUES (?)", (store,))

    def _get(self, store: str, product_id: str) -> bool | None:
        row = self._conn.execute(
            "SELECT in_stock FROM observations WHERE store = ? AND product_id = ?",
            (store, product_id),
        ).fetchone()
        if row is None:
            return None
        return bool(row[0])

    def _set(self, store: str, product_id: str, in_stock: bool) -> None:
        self._conn.execute(
            """
            INSERT INTO observations (store, product_id, in_stock)
            VALUES (?, ?, ?)
            ON CONFLICT(store, product_id) DO UPDATE SET in_stock = excluded.in_stock
            """,
            (store, product_id, int(in_stock)),
        )
