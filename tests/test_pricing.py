from taximan.pricing import MIN_FARE_CENTS, quote_cents


def test_minimum_fare():
    assert quote_cents(0.1, 60) == MIN_FARE_CENTS


def test_formula_and_rounding():
    # 350 + 95*4.2 + 25*10 = 999 cents
    assert quote_cents(4.2, 600) == 999
    # surge 1.5 -> 1498.5 rounds half up to 1499
    assert quote_cents(4.2, 600, 1.5) == 1499


def test_returns_int():
    assert isinstance(quote_cents(3, 300, 1.25), int)
