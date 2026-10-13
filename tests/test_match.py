from pokegrab.match import msrp_for, name_matches, price_in_range


def test_msrp_prefers_longest_product_type():
    table = {"elite trainer box": 49.99, "pokemon center elite trainer box": 59.99, "tin": 26.99, "mini tin": 9.99}
    assert msrp_for("Pokemon Center Elite Trainer Box", table) == 59.99
    assert msrp_for("Pokemon Elite Trainer Box", table) == 49.99
    assert msrp_for("Pokemon Mini Tin Pikachu", table) == 9.99
    assert msrp_for("Pokemon booster pack", table) is None


def test_hyphen_and_accent_variants_match():
    assert name_matches("Pokémon Ultra-Premium Collection", ["pokemon ultra premium collection"], [])


def test_phrase_keyword_matches():
    assert name_matches("Pokemon TCG Elite Trainer Box", ["elite trainer box"], [])


def test_single_word_uses_word_boundaries():
    assert name_matches("Paldean Fates Mini Tin", ["tin"], [])
    assert not name_matches("Something else", ["tin"], [])
    assert not name_matches("That product", ["hat"], [])


def test_exclude_term_rejects_match():
    assert not name_matches("Pokemon Plush Elite Trainer Box", ["elite trainer box"], ["plush"])
    assert not name_matches("Pokemon hat", ["hat"], ["hat"])


def test_price_range_allows_unknown_price():
    assert price_in_range(None, 10, 100)
    assert price_in_range(25, 10, 100)
    assert not price_in_range(5, 10, None)
    assert not price_in_range(150, None, 100)
