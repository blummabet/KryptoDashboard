import clv


def _snap(cid, fair, poly, edge):
    return {"conditionId": cid, "fairProb": fair, "polyPrice": poly, "edgePP": edge}


def test_movement_clv():
    groups = {"A": [_snap("A", 0.40, 0.30, 10.0), _snap("A", 0.40, 0.36, 4.0)]}
    picks = clv._movement_clv(groups)
    assert picks[0]["clvPP"] == 6.0  # Poly bewegt sich +6pp Richtung Fair (Yes-Pick)


def test_movement_clv_short_side():
    # edge<0 = Yes überbepreist → No-Pick; Poly fällt → positiver CLV
    groups = {"B": [_snap("B", 0.60, 0.70, -10.0), _snap("B", 0.60, 0.64, -4.0)]}
    assert clv._movement_clv(groups)[0]["clvPP"] == 6.0


def test_calibration():
    groups = {"A": [_snap("A", 0.40, 0.30, 10.0)], "B": [_snap("B", 0.60, 0.70, -10.0)]}
    res = {"A": {"outcome": 1}, "B": {"outcome": 0}}
    cal = clv._calibration(groups, res)
    assert cal["resolvedPicks"] == 2
    assert cal["hitRate"] == 1.0
    assert cal["betterThanPoly"] > 0  # Fair besser kalibriert als Poly-Preis


def test_trends_last_points():
    groups = {"A": [_snap("A", 0.4, 0.3, 1.0), _snap("A", 0.4, 0.3, 2.0)]}
    assert clv._trends(groups)["A"] == [1.0, 2.0]
