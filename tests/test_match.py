from pokegrab.match import name_matches, price_in_range


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
