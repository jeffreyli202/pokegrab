import sqlite3
from pathlib import Path

from pokegrab.config import Settings
from pokegrab.match import name_matches, price_in_range
from pokegrab.models import Product


class StockState:
    def __init__(self, path: str):
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
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
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def observe(self, store: str, products: list[Product], settings: Settings) -> list[Product]:
        baselined = self._is_baselined(store)
        alerts: list[Product] = []
        for product in products:
            if not name_matches(product.name, settings.keywords, settings.exclude):
                continue
            previous = self._get(store, product.id)
            if not baselined:
                self._set(store, product.id, bool(product.in_stock))
                continue
            in_range = price_in_range(product.price, settings.price_min, settings.price_max)
            if product.in_stock is True and in_range and previous is not True:
                alerts.append(product)
                self._set(store, product.id, True)
            elif product.in_stock is False:
                self._set(store, product.id, False)
        if not baselined:
            self._mark_baselined(store)
        self._conn.commit()
        return alerts

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
