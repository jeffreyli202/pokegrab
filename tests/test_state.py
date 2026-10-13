from pokegrab.config import Settings
from pokegrab.models import Product
from pokegrab.state import StockState, title_fingerprint

HOUR = 3600


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
        ebay_client_id="",
        ebay_client_secret="",
        alert_cooldown_hours=0,
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


def listing(listing_id, name="Pokemon Mini Tin Day Pikachu") -> Product:
    return Product(
        store="eBay",
        id=listing_id,
        name=name,
        price=9.99,
        url=f"https://www.ebay.com/itm/{listing_id}",
        image=None,
        in_stock=True,
        msrp=9.99,
        shipping=0,
    )


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def scan(state, store, products, config, **options) -> list[str]:
    """Observe and record every alert, the way the bot does after Discord accepts it."""
    alerts = state.observe(store, products, config, **options)
    for item in alerts:
        state.record_alert(store, item, dedupe_by_title=options.get("dedupe_by_title", False))
    return [item.id for item in alerts]


def test_first_scan_baselines_without_alerts(tmp_path):
    state = StockState(tmp_path / "state.db")
    assert scan(state, "bestbuy", [product("1"), product("2", in_stock=False)], settings()) == []
    state.close()


def test_new_in_stock_product_alerts_after_baseline(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [product("1")], config)
    assert scan(state, "bestbuy", [product("1"), product("2")], config) == ["2"]
    state.close()


def test_same_in_stock_product_does_not_alert_again(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [], config)
    scan(state, "bestbuy", [product("1")], config)
    assert scan(state, "bestbuy", [product("1")], config) == []
    state.close()


def test_restock_after_out_of_stock_alerts_without_cooldown(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == ["1"]
    assert scan(state, "bestbuy", [product("1")], config) == []
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == ["1"]
    state.close()


def test_unsent_alert_is_offered_again_next_scan(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [], config)
    assert [item.id for item in state.observe("bestbuy", [product("1")], config)] == ["1"]
    assert [item.id for item in state.observe("bestbuy", [product("1")], config)] == ["1"]
    state.close()


def test_restock_inside_cooldown_is_skipped(tmp_path):
    clock = Clock()
    state = StockState(tmp_path / "state.db", clock=clock)
    config = settings(alert_cooldown_hours=6)
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == ["1"]

    clock.now += 2 * HOUR
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == []
    # Still in stock from the skipped restock, so the cooldown ending alone does not post it.
    clock.now += 5 * HOUR
    assert scan(state, "bestbuy", [product("1")], config) == []
    state.close()


def test_restock_after_cooldown_alerts_again(tmp_path):
    clock = Clock()
    state = StockState(tmp_path / "state.db", clock=clock)
    config = settings(alert_cooldown_hours=6)
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == ["1"]

    clock.now += 7 * HOUR
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    assert scan(state, "bestbuy", [product("1")], config) == ["1"]
    state.close()


def test_cooldown_survives_restart(tmp_path):
    clock = Clock()
    config = settings(alert_cooldown_hours=6)
    state = StockState(tmp_path / "state.db", clock=clock)
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    scan(state, "bestbuy", [product("1")], config)
    scan(state, "bestbuy", [product("1", in_stock=False)], config)
    state.close()

    clock.now += HOUR
    state = StockState(tmp_path / "state.db", clock=clock)
    assert scan(state, "bestbuy", [product("1")], config) == []
    state.close()


def test_price_outside_range_waits_until_price_is_allowed(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [], config)
    assert scan(state, "bestbuy", [product("1", price=150)], config) == []
    assert scan(state, "bestbuy", [product("1", price=40)], config) == ["1"]
    state.close()


def test_msrp_listing_alerts_on_first_scan_without_repeating(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    assert scan(state, "ebay", [listing("v1|1|0")], config, baseline=False) == ["v1|1|0"]
    assert scan(state, "ebay", [listing("v1|1|0")], config, baseline=False) == []
    state.close()


def test_relisted_title_waits_for_cooldown(tmp_path):
    clock = Clock()
    state = StockState(tmp_path / "state.db", clock=clock)
    config = settings(alert_cooldown_hours=6)
    options = {"baseline": False, "dedupe_by_title": True}
    assert scan(state, "ebay", [listing("v1|1|0")], config, **options) == ["v1|1|0"]

    clock.now += HOUR
    relist = listing("v1|2|0", "NEW Sealed Pokemon Mini Tin - Day Pikachu FREE SHIPPING")
    assert scan(state, "ebay", [relist], config, **options) == []

    clock.now += 6 * HOUR
    later = listing("v1|3|0", "Pokemon Mini Tin Day Pikachu")
    assert scan(state, "ebay", [later], config, **options) == ["v1|3|0"]
    state.close()


def test_duplicate_titles_in_one_scan_post_once(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings(alert_cooldown_hours=6)
    options = {"baseline": False, "dedupe_by_title": True}
    alerts = scan(state, "ebay", [listing("v1|1|0"), listing("v1|2|0")], config, **options)
    assert alerts == ["v1|1|0"]
    state.close()


def test_different_products_are_not_merged():
    assert title_fingerprint("Pokemon Mini Tin Day Pikachu") != title_fingerprint("Pokemon Mini Tin Night Umbreon")
    assert title_fingerprint("NEW Pokemon Mini Tin Day Pikachu SEALED") == title_fingerprint(
        "Pokémon Mini Tin - Day Pikachu"
    )


def test_msrp_listing_does_not_need_a_global_keyword(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings(keywords=["elite trainer box"])
    high_class = listing("v1|9|0", "Pokemon MEGA Dream ex High Class Pack Box Japanese")
    assert scan(state, "ebay", [high_class], config, baseline=False) == ["v1|9|0"]
    plush = listing("v1|10|0", "Pokemon High Class Pack Plush Japanese")
    assert scan(state, "ebay", [plush], config, baseline=False) == []
    state.close()


def test_excluded_name_is_ignored(tmp_path):
    state = StockState(tmp_path / "state.db")
    config = settings()
    scan(state, "bestbuy", [], config)
    plush = product("1", name="Pokemon Plush Elite Trainer Box")
    assert scan(state, "bestbuy", [plush], config) == []
    state.close()
