import consistency
import maker


def _m(cid, strike, poly, family="above", direction="above", end="2026-07-31T16:00:00Z",
       fair=None, bid=None, ask=None, liq=50000):
    return {"conditionId": cid, "market": f"K{strike}", "strike": strike, "polyPrice": poly,
            "family": family, "direction": direction, "endDate": end, "fairProb": fair,
            "bestBid": bid, "bestAsk": ask, "liquidityUSD": liq,
            "rewardsMaxSpread": 4.5, "rewardsMinSize": 50}


def test_consistency_finds_inversion():
    # above: höherer Strike muss billiger sein; hier ist er teurer → Widerspruch
    f = consistency.scan([_m("A", 60000, 0.30), _m("B", 64000, 0.45)])
    assert len(f) == 1 and f[0]["lowStrike"] == 60000 and f[0]["gapPP"] == 15.0
    assert f[0]["tradable"] is True


def test_consistency_clean_ladder_no_findings():
    assert consistency.scan([_m("A", 60000, 0.80), _m("B", 64000, 0.55), _m("C", 68000, 0.30)]) == []


def test_consistency_dip_direction():
    # dip: höherer Strike (näher am Spot) muss wahrscheinlicher sein; hier fällt er → Widerspruch
    f = consistency.scan([_m("A", 45000, 0.30, family="touch", direction="below"),
                          _m("B", 58000, 0.10, family="touch", direction="below")])
    assert len(f) == 1


def test_maker_board_quotes_around_mid_skew_by_fair():
    r = maker.board([_m("A", 60000, 0.50, fair=0.52, bid=0.49, ask=0.51)])[0]
    assert r["quoteBid"] < r["mid"] < r["quoteAsk"]   # um die MITTE (LRP scored Nähe zur Mitte)
    assert r["skew"] == "bid"                          # fair > mid → mehr Größe auf den Bid
    assert r["edgeIfFilledPP"] > 0 and r["rewardEligible"] is True


def test_maker_reward_share_weighted():
    thin = maker.board([_m("T", 60000, 0.50, fair=0.53, bid=0.49, ask=0.51, liq=2000)])[0]
    thick = maker.board([_m("K", 60000, 0.50, fair=0.53, bid=0.49, ask=0.51, liq=80000)])[0]
    assert thin["estRewardDay"] > thick["estRewardDay"]   # dünn = höherer Anteil = mehr Reward


def _nr(cid, poly, bid, ask, eid="EV1", title="Bucket-Event"):
    """Ein NegRisk-Bucket (exklusives Outcome eines Events)."""
    return {"conditionId": cid, "market": f"M{cid}", "polyPrice": poly, "eventId": eid,
            "eventTitle": title, "negRisk": True, "bestBid": bid, "bestAsk": ask,
            "clobTokenIds": [f"y{cid}", f"n{cid}"]}


def test_negrisk_buy_basket_underpriced():
    # Σ Yes-Ask = 0.30+0.30+0.30 = 0.90 < 1 → Basket kaufen, 10pp risikofrei
    f = consistency.scan_negrisk([_nr("A", 0.29, 0.28, 0.30), _nr("B", 0.29, 0.28, 0.30),
                                  _nr("C", 0.29, 0.28, 0.30)])
    assert len(f) == 1 and f[0]["side"] == "buy"
    assert f[0]["gapPP"] == 10.0 and f[0]["tradable"] is True and f[0]["n"] == 3


def test_negrisk_sell_basket_overpriced():
    # Σ Yes-Bid = 0.40+0.40+0.40 = 1.20 > 1 → Basket verkaufen, 20pp risikofrei
    f = consistency.scan_negrisk([_nr("A", 0.41, 0.40, 0.42), _nr("B", 0.41, 0.40, 0.42),
                                  _nr("C", 0.41, 0.40, 0.42)])
    assert len(f) == 1 and f[0]["side"] == "sell" and f[0]["gapPP"] == 20.0


def test_negrisk_fair_basket_no_arb():
    # Σ Yes-Ask = 1.02 (nicht < 1), Σ Yes-Bid = 0.99 (nicht > 1) → kein Arb
    assert consistency.scan_negrisk([_nr("A", 0.34, 0.33, 0.34), _nr("B", 0.34, 0.33, 0.34),
                                     _nr("C", 0.34, 0.33, 0.34)]) == []


def test_negrisk_ignores_nested_ladders():
    # negRisk=false (verschachtelte Leiter, der reale Krypto-Fall) → nie ein Basket-Fund
    ladder = [_m("A", 60000, 0.30), _m("B", 64000, 0.45)]  # kein negRisk/eventId
    assert consistency.scan_negrisk(ladder) == []
