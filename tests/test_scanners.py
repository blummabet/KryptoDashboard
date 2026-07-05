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
