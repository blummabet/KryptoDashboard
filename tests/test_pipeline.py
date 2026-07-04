import build_markets as bm
import resolutions as rz


def test_parse_strike():
    assert bm.parse_strike({"groupItemTitle": "110,000"}) == (110000, "above")
    assert bm.parse_strike({"groupItemTitle": "↑ 6,000"}) == (6000, "above")
    assert bm.parse_strike({"groupItemTitle": "↓ 40"}) == (40, "below")


def test_yes_price():
    assert bm.yes_price({"outcomePrices": '["0.505", "0.495"]'}) == 0.505
    assert bm.yes_price({}) is None
    assert bm.yes_price({"outcomePrices": "kaputt"}) is None


def test_resolution_outcome():
    assert rz._outcome({"closed": True, "outcomePrices": '["1", "0"]'}) == 1
    assert rz._outcome({"closed": True, "outcomePrices": '["0", "1"]'}) == 0
    assert rz._outcome({"closed": False, "outcomePrices": '["0.5", "0.5"]'}) is None
    assert rz._outcome(None) is None
