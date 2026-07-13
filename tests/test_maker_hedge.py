import maker


def test_delta_above_positive():
    m = {"strike": 60000, "ivPct": 60, "daysLeft": 30, "family": "above", "direction": "above"}
    assert maker._delta(m, 60000) > 0


def test_delta_dip_negative():
    # Touch-"dip" (Barriere unter Spot): steigt Spot, sinkt die Dip-Wkt. → Delta < 0
    m = {"strike": 55000, "ivPct": 60, "daysLeft": 30, "family": "touch", "direction": "below"}
    assert maker._delta(m, 60000) < 0


def test_delta_none_on_missing():
    assert maker._delta({"strike": None, "ivPct": 60, "daysLeft": 30}, 60000) is None


def _row(cid, mid, delta=0.0001, spot=60000, sel=True):
    return {"conditionId": cid, "mid": mid, "fair": mid, "delta": delta, "spot": spot,
            "rewardEligible": True, "makerSelect": sel}


# ── Phase 2: Fill-Erkennung ──────────────────────────────────────────────────────────────
def test_detects_buy_fill_into_pending():
    # prevMid 0.50 → Bid 0.48; Mid fällt auf 0.40 → BUY @ 0.48 landet in der Warteschlange
    s = maker.markout_step([_row("A", 0.40)], {"A": 0.50}, 60500, pending=[])
    assert s["fills"] == 0                     # noch nichts bewertet
    assert len(s["newPending"]) == 1
    p = s["newPending"][0]
    assert p["side"] == "BUY" and abs(p["fillPrice"] - 0.48) < 1e-9
    assert p["hedgeNotionalUSD"] > 0           # Hedge-Notional mitgeschrieben


def test_no_fill_when_price_stays_inside_quote():
    s = maker.markout_step([_row("A", 0.50)], {"A": 0.50}, 60000, pending=[])
    assert s["newPending"] == [] and s["fills"] == 0


# ── Phase 1: Markout gegen den KÜNFTIGEN Markt-Mid (nicht gegen unsere Fair) ─────────────
def test_markout_vs_future_mid_not_our_fair():
    # Offener BUY-Fill @ 0.48; der Mid erholt sich auf 0.52 → Markout +4pp (unabhängig von 'fair'!)
    pend = [{"cid": "A", "side": "BUY", "fillPrice": 0.48, "spotAtFill": 60000,
             "delta": 0.0, "select": True, "hedgeNotionalUSD": 0.0}]
    row = _row("A", 0.52)
    row["fair"] = 0.99          # absichtlich absurde Fair — darf das Ergebnis NICHT beeinflussen
    s = maker.markout_step([row], {}, 60000, pending=pend)
    assert s["fills"] == 1 and abs(s["rawSum"] - 4.0) < 1e-6


def test_adverse_fill_is_negative():
    # BUY @ 0.48, Mid fällt weiter auf 0.44 → Markout −4pp (echte Adverse Selection)
    pend = [{"cid": "A", "side": "BUY", "fillPrice": 0.48, "spotAtFill": 60000,
             "delta": 0.0, "select": True, "hedgeNotionalUSD": 0.0}]
    s = maker.markout_step([_row("A", 0.44)], {}, 60000, pending=pend)
    assert abs(s["rawSum"] - (-4.0)) < 1e-6


def test_hedge_removes_spot_driven_part():
    # BUY @ 0.48; Mid fällt auf 0.44 (−4pp), aber BTC fiel 500 → delta 0.0001 erklärt −5pp davon.
    # gehedged = roh − (delta·Δspot·100) = −4 − (−5) = +1
    pend = [{"cid": "A", "side": "BUY", "fillPrice": 0.48, "spotAtFill": 60500,
             "delta": 0.0001, "select": True, "hedgeNotionalUSD": 0.0}]
    s = maker.markout_step([_row("A", 0.44, spot=60000)], {}, 60000, pending=pend)
    assert abs(s["rawSum"] - (-4.0)) < 1e-6
    assert abs(s["hedgedSum"] - 1.0) < 1e-6
    assert s["hedgedSum"] > s["rawSum"]


def test_sell_side_hedge_sign():
    # SELL @ 0.52; Mid steigt auf 0.56 → roh = 0.52−0.56 = −4pp. BTC stieg 500, delta 0.0001 → +5pp
    # gehedged = roh + hedge = −4 + 5 = +1
    pend = [{"cid": "A", "side": "SELL", "fillPrice": 0.52, "spotAtFill": 59500,
             "delta": 0.0001, "select": False, "hedgeNotionalUSD": 0.0}]
    s = maker.markout_step([_row("A", 0.56, spot=60000)], {}, 60000, pending=pend)
    assert abs(s["rawSum"] - (-4.0)) < 1e-6
    assert abs(s["hedgedSum"] - 1.0) < 1e-6
    assert s["selFills"] == 0              # nicht selektiv → nicht im selektiven Topf


def test_selective_routing_and_notional_sum():
    pend = [
        {"cid": "A", "side": "BUY", "fillPrice": 0.48, "spotAtFill": 60000, "delta": 0.0,
         "select": True, "hedgeNotionalUSD": 400.0},
        {"cid": "B", "side": "BUY", "fillPrice": 0.48, "spotAtFill": 60000, "delta": 0.0,
         "select": False, "hedgeNotionalUSD": 200.0},
    ]
    s = maker.markout_step([_row("A", 0.52), _row("B", 0.52)], {}, 60000, pending=pend)
    assert s["fills"] == 2 and s["selFills"] == 1
    assert s["hedgeNotionalUSD"] == 600.0


def test_pending_fill_on_vanished_market_is_dropped():
    pend = [{"cid": "GONE", "side": "BUY", "fillPrice": 0.5, "spotAtFill": 60000,
             "delta": 0.0, "select": True, "hedgeNotionalUSD": 0.0}]
    s = maker.markout_step([_row("A", 0.5)], {}, 60000, pending=pend)
    assert s["fills"] == 0
