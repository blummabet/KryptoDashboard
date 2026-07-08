import maker


def test_delta_above_positive():
    # Digital "über": faire Wkt. STEIGT mit Spot → Delta > 0
    m = {"strike": 60000, "ivPct": 60, "daysLeft": 30, "family": "above", "direction": "above"}
    assert maker._delta(m, 60000) > 0


def test_delta_dip_negative():
    # Touch-"dip" (Barriere unter Spot): steigt Spot, sinkt die Dip-Wkt. → Delta < 0
    m = {"strike": 55000, "ivPct": 60, "daysLeft": 30, "family": "touch", "direction": "below"}
    assert maker._delta(m, 60000) < 0


def test_delta_none_on_missing():
    assert maker._delta({"strike": None, "ivPct": 60, "daysLeft": 30}, 60000) is None


def _row(cid, mid, fair, delta, sel=True):
    return {"conditionId": cid, "mid": mid, "fair": fair, "delta": delta, "spot": 60000,
            "rewardEligible": True, "makerSelect": sel}


def test_hedge_recovers_spot_driven_buy():
    # BUY-Fill (Preis fiel durch Bid) + BTC fiel 500 → roher Markout adverse, Hedge holt Spot-Teil zurück
    b = [_row("A", 0.40, 0.40, 0.0001)]
    # prevMid 0.50 → pb=0.48; mid 0.40 ≤ 0.48 → BUY. prevSpot 60500 → dspot −500.
    s = maker.markout_step(b, {"A": 0.50}, 60500)
    assert s["fills"] == 1
    raw = s["rawSum"]; hedged = s["hedgedSum"]
    assert raw < 0                      # adverse
    assert hedged > raw                 # Hedge verbessert
    # raw=(0.40−0.48)*100=−8 ; hedge_pp=0.0001*(−500)*100=−5 ; hedged=−8−(−5)=−3
    assert abs(raw - (-8.0)) < 1e-6 and abs(hedged - (-3.0)) < 1e-6


def test_hedge_recovers_spot_driven_sell():
    b = [_row("A", 0.60, 0.60, 0.0001)]
    # prevMid 0.50 → pa=0.52; mid 0.60 ≥ 0.52 → SELL. prevSpot 59500 → dspot +500.
    s = maker.markout_step(b, {"A": 0.50}, 59500)
    assert s["fills"] == 1 and s["hedgedSum"] > s["rawSum"]
    assert abs(s["rawSum"] - (-8.0)) < 1e-6 and abs(s["hedgedSum"] - (-3.0)) < 1e-6


def test_selective_routing():
    # nur die selektive Position landet im selektiven Topf
    b = [_row("A", 0.40, 0.40, 0.0001, sel=True), _row("B", 0.40, 0.40, 0.0001, sel=False)]
    s = maker.markout_step(b, {"A": 0.50, "B": 0.50}, 60500)
    assert s["fills"] == 2 and s["selFills"] == 1


def test_no_fill_when_price_stays():
    # Preis bleibt in der Quote → kein Fill
    b = [_row("A", 0.50, 0.50, 0.0001)]
    s = maker.markout_step(b, {"A": 0.50}, 60000)
    assert s["fills"] == 0
