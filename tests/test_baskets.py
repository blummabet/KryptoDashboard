import baskets


def _cand(name, bid, ask, key="EV1", title="Wer wird Weltmeister?", rate=0.03):
    """Ein negRisk-Kandidat (flaches Gamma-Market-Format)."""
    return {"groupItemTitle": name, "question": f"Will {name} win?", "bestBid": bid, "bestAsk": ask,
            "negRisk": True, "negRiskMarketID": key, "closed": False,
            "clobTokenIds": f'["y{name}","n{name}"]', "conditionId": f"c{name}",
            "feeSchedule": {"rate": rate, "takerOnly": True},
            "events": [{"id": "30615", "slug": "wc", "title": title, "endDate": "2026-07-20T00:00:00Z"}]}


def test_sell_basket_overpriced_is_robust():
    # Σ Yes-Bid = 0.40*3 = 1.20 > 1 → SELL-Basket, robust risikofrei
    f = baskets.scan([_cand("A", 0.40, 0.42), _cand("B", 0.40, 0.42), _cand("C", 0.40, 0.42)])
    assert len(f) == 1 and f[0]["side"] == "sell"
    assert f[0]["grossPP"] == 20.0 and f[0]["exhaustiveNeeded"] is False
    assert f[0]["netPP"] < f[0]["grossPP"]        # Fee zieht ab
    assert f[0]["tradable"] is True               # sell-Seite + großer Gap


def test_buy_basket_underpriced_needs_exhaustive():
    # Σ Yes-Ask = 0.30*3 = 0.90 < 1 → BUY-Basket, aber NUR bei erschöpfenden Kandidaten
    f = baskets.scan([_cand("A", 0.28, 0.30), _cand("B", 0.28, 0.30), _cand("C", 0.28, 0.30)])
    assert len(f) == 1 and f[0]["side"] == "buy"
    assert f[0]["exhaustiveNeeded"] is True
    assert f[0]["tradable"] is False              # buy-Seite nie als "robust handelbar"


def test_fair_basket_no_finding():
    # Σ Ask = 1.02 (kein Buy), Σ Bid = 0.99 (kein Sell) → nichts
    assert baskets.scan([_cand("A", 0.33, 0.34), _cand("B", 0.33, 0.34), _cand("C", 0.33, 0.34)]) == []


def test_incomplete_bid_not_tradable():
    # ein Bein ohne Bid → Σ unvollständig → KEIN sell-Fund (man könnte nicht alle Beine shorten)
    ms = [_cand("A", 0.40, 0.42), _cand("B", 0.40, 0.42), _cand("C", None, 0.42)]
    f = baskets.scan(ms)
    # completeBid False → sell-Zweig greift nicht; buy-Zweig: Σ Ask=1.26 > 1 → auch nichts
    assert f == []


def test_min_legs_guard():
    # 2 Kandidaten < MIN_LEGS → kein Basket
    assert baskets.scan([_cand("A", 0.40, 0.42), _cand("B", 0.40, 0.42)]) == []


def test_groups_by_negrisk_id():
    # zwei getrennte Events → getrennt bewertet
    ms = ([_cand("A", 0.40, 0.42, key="EV1"), _cand("B", 0.40, 0.42, key="EV1"),
           _cand("C", 0.40, 0.42, key="EV1")] +
          [_cand("X", 0.33, 0.34, key="EV2"), _cand("Y", 0.33, 0.34, key="EV2"),
           _cand("Z", 0.33, 0.34, key="EV2")])   # EV2 fair bepreist → kein Fund
    f = baskets.scan(ms)
    assert len(f) == 1 and f[0]["negRiskMarketID"] == "EV1"   # nur EV1 hat Σ≠1-Arb
