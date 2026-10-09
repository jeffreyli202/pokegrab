from pokegrab.config import Settings
from pokegrab.models import Product
from pokegrab.state import StockState


def settings(**overrides) -> Settings:
    data = dict(
        poll_seconds=180,
        price_min=10,
        price_max=100,
        keywords=["elite trainer box", "booster bundle", "tin"],
        exclude=["plush"],
        stores={},
        database=":memory:",
        discord_webhook_url="",
        bestbuy_api_key="",
        amazon_credential_id="",
        amazon_credential_secret="",
        amazon_partner_tag="",
        amazon_credential_version="3.1",
    )
    data.update(overrides)
    return Settings(**data)


def product(product_id, *, name="Pokemon TCG Elite Trainer Box", price=49.99, in_stock=True) -> Product:
    return Product(
        store="Best Buy",
        id=product_id,
        name=name,
        price=price,
        url=f"https://example.com/{product_id}",
        image=None,
        in_stock=in_stock,
    )


def test_first_scan_baselines_without_alerts(tmp_path):
    state = StockState(tmp_path / "state.db")
    alerts = state.observe("bestbuy", [product("1"), product("2", in_stock=False)], settings())
    assert alerts == []
    state.close()


def test_new_in_stock_product_alerts_after_baseline(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    state.observe("bestbuy", [product("1")], config)
    alerts = state.observe("bestbuy", [product("1"), product("2")], config)
    assert [item.id for item in alerts] == ["2"]
    state.close()


def test_same_in_stock_product_does_not_alert_again(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    state.observe("bestbuy", [], config)
    state.observe("bestbuy", [product("1")], config)
    alerts = state.observe("bestbuy", [product("1")], config)
    assert alerts == []
    state.close()


def test_restock_after_out_of_stock_alerts(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    state.observe("bestbuy", [product("1", in_stock=False)], config)
    assert state.observe("bestbuy", [product("1", in_stock=True)], config)[0].id == "1"
    assert state.observe("bestbuy", [product("1", in_stock=True)], config) == []
    state.observe("bestbuy", [product("1", in_stock=False)], config)
    assert state.observe("bestbuy", [product("1", in_stock=True)], config)[0].id == "1"
    state.close()


def test_price_outside_range_waits_until_price_is_allowed(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    state.observe("bestbuy", [], config)
    assert state.observe("bestbuy", [product("1", price=150)], config) == []
    alerts = state.observe("bestbuy", [product("1", price=40)], config)
    assert [item.id for item in alerts] == ["1"]
    state.close()


def test_excluded_name_is_ignored(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    state.observe("bestbuy", [], config)
    plush = product("1", name="Pokemon Plush Elite Trainer Box")
    assert state.observe("bestbuy", [plush], config) == []
    state.close()
