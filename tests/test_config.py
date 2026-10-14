from pathlib import Path

import pytest

from pokegrab.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_loads():
    settings = load_settings(ROOT / "config.example.yaml", load_env=False)
    assert "elite trainer box" in settings.keywords
    assert settings.poll_seconds == 60
    assert settings.poll_seconds_for("ebay") == 240
    assert settings.poll_seconds_for("bestbuy") == 60
    assert settings.price_min == 10
    assert settings.price_max is None
    assert settings.stores["target"] is True


def test_example_config_filters_ebay_accessories():
    settings = load_settings(ROOT / "config.example.yaml", load_env=False)
    assert settings.ebay_min_percent_of_msrp == 60
    assert "playmat" in settings.ebay_exclude
    assert "dice" in settings.ebay_exclude


def test_example_config_includes_asian_editions():
    settings = load_settings(ROOT / "config.example.yaml", load_env=False)
    assert "japanese" not in settings.ebay_exclude
    japanese = settings.ebay_editions["japanese"]
    assert japanese.msrp["booster box"] == 37.97
    assert japanese.max_markup_percent == 60
    assert settings.ebay_editions["korean"].msrp["booster box"] == 22.49
    assert "high class pack" in settings.ebay_extra_searches


def test_example_msrp_prices_specific_collections():
    from pokegrab.match import msrp_for

    table = load_settings(ROOT / "config.example.yaml", load_env=False).ebay_msrp
    assert msrp_for("Pokemon 30th Celebration Knock Out Collection Box Eevee", table) == 9.99
    assert msrp_for("Pokemon TCG Knockout Collection", table) == 9.99
    assert msrp_for("Pokemon Ditto Premium Collection", table) == 39.99
    assert msrp_for("Pokemon 30th Celebration Ultra-Premium Collection Day", table) == 179.99
    assert msrp_for("Pokemon Sylveon ex Box 30th Celebration", table) == 21.99
    assert msrp_for("Pokemon 2-Pack Blister Eevee", table) == 9.99
    assert msrp_for("Pokemon Charizard Collection Box", table) == 29.99
    assert msrp_for("Prismatic Evolutions Super-Premium Collection SPC", table) == 89.99
    assert msrp_for("Pokemon Mega Charizard ex Premium Collection Box", table) == 39.99
    assert msrp_for("Pokemon Build & Battle Box Phantasmal Flames", table) == 21.99
    assert msrp_for("Pokemon 3 Pack Blister Pikachu", table) == 13.99
    assert msrp_for("Pokemon Sylveon ex Tin 30th Celebration", table) == 21.99
    assert msrp_for("Pokemon Pokemon Center Elite Trainer Box", table) == 59.99


def test_poll_interval_is_at_least_one_minute(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("poll_seconds: 5\nkeywords:\n  - tin\n", encoding="utf-8")
    settings = load_settings(path, load_env=False)
    assert settings.poll_seconds == 60


def test_store_poll_overrides(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "poll_seconds: 120\nstore_poll_seconds:\n  ebay: 300\n  target: 10\nkeywords:\n  - tin\n",
        encoding="utf-8",
    )
    settings = load_settings(path, load_env=False)
    assert settings.poll_seconds_for("ebay") == 300
    assert settings.poll_seconds_for("target") == 60
    assert settings.poll_seconds_for("walmart") == 120


def test_store_poll_overrides_reject_unknown_store(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("store_poll_seconds:\n  costco: 90\nkeywords:\n  - tin\n", encoding="utf-8")
    with pytest.raises(ValueError, match="costco"):
        load_settings(path, load_env=False)


def test_keywords_are_required(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("keywords: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path, load_env=False)
