from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    store: str
    id: str
    name: str
    price: float | None
    url: str
    image: str | None
    in_stock: bool | None


def dedupe_products(products: list[Product]) -> list[Product]:
    found: dict[str, Product] = {}
    for product in products:
        current = found.get(product.id)
        if current is None or (current.in_stock is not True and product.in_stock is True):
            found[product.id] = product
    return list(found.values())
