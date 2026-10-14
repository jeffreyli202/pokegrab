from pokegrab.config import load_settings
from pokegrab.discord import payload_for
from pokegrab.monitors.dollargeneral import parse_dollargeneral_payload
from pokegrab.state import StockState
from tests.test_config import ROOT
from tests.test_loop import settings

PAYLOAD = {
    "Items": [
        {
            "UPC": 728192558375,
            "sku": "41936301",
            "Description": "Pokémon Trading Card Game, 15 Card Pack, 1 ct",
            "Price": 8.0,
            "Image": "https://s7d1.scene7.com/is/image/dolgen/dg-41936301-1",
            "AvailableStockStore": 5,
        },
        {
            "sku": "41936302",
            "Description": "Pokémon TCG Mini Tin, 1 ct",
            "Price": 10.0,
            "AvailableStockStore": 0,
        },
        {"sku": "41917101", "Description": "HERSHEY'S Milk Chocolate Pokemon, Candy Bar, 1.55 oz", "Price": 1.75},
        {"sku": "41900001", "Description": "Pokémon Pikachu Plush, 8 in", "Price": 10.0, "AvailableStockStore": 3},
        {"sku": "40000001", "Description": "Magic Trading Card Booster", "Price": 5.0, "AvailableStockStore": 2},
    ]
}


def test_parse_keeps_pokemon_cards_with_store_counts():
    products = parse_dollargeneral_payload(PAYLOAD, "13585", "4115 N El Dorado St, Stockton")
    assert [p.id for p in products] == ["13585:41936301", "13585:41936302"]
    pack, tin = products
    assert pack.store == "Dollar General · 4115 N El Dorado St, Stockton"
    assert pack.price == 8.0
    assert pack.quantity == 5
    assert pack.in_stock is True
    assert tin.quantity == 0
    assert tin.in_stock is False


def test_restock_alerts_even_below_price_min_and_without_keywords(tmp_path):
    config = settings(tmp_path, price_min=10, keywords=["elite trainer box"])
    state = StockState(config.database)
    empty = {"Items": [dict(PAYLOAD["Items"][0], AvailableStockStore=0)]}
    first = parse_dollargeneral_payload(empty, "13585", "El Dorado")
    assert state.observe("dollargeneral", first, config, prefiltered=True) == []
    restocked = parse_dollargeneral_payload(PAYLOAD, "13585", "El Dorado")
    alerts = state.observe("dollargeneral", restocked, config, prefiltered=True)
    assert [p.id for p in alerts] == ["13585:41936301"]
    state.close()


def test_same_item_at_two_stores_are_separate_products():
    a = parse_dollargeneral_payload(PAYLOAD, "13585", "El Dorado")[0]
    b = parse_dollargeneral_payload(PAYLOAD, "13593", "Alpine")[0]
    assert a.id != b.id


def test_discord_shows_shelf_count():
    pack = parse_dollargeneral_payload(PAYLOAD, "13585", "El Dorado")[0]
    description = payload_for(pack)["embeds"][0]["description"]
    assert "**Dollar General · El Dorado** · $8.00" in description
    assert "5 on the shelf" in description


def test_example_config_lists_stockton_stores():
    config = load_settings(ROOT / "config.example.yaml", load_env=False)
    assert config.stores["dollargeneral"] is True
    assert config.dollargeneral_stores["13585"] == "4115 N El Dorado St, Stockton"
    assert len(config.dollargeneral_stores) == 5
    assert "trading card" in config.dollargeneral_include
    assert config.poll_seconds_for("dollargeneral") == 300
