import rewards


def test_order_score_quadratic_and_zero_outside_band():
    v = 0.03
    assert abs(rewards.order_score(100, 0.0, v) - 100) < 1e-9
    assert rewards.order_score(100, v, v) == 0.0
    assert abs(rewards.order_score(100, v / 2, v) - 25.0) < 1e-9   # (0.5)² · size
    assert rewards.order_score(100, v * 1.5, v) == 0.0


def test_reward_share_is_tiny_against_big_liquidity():
    # $500 gegen $500k Liquidität → Bruchteil eines Prozents, NICHT 60%
    share = rewards.reward_share(500, 500_000)
    assert share < 0.002            # < 0.2 %
    # gegen sehr kleine Liquidität greift der Floor (nie mehr als 50 %)
    assert rewards.reward_share(500, 0) <= 0.5


def test_markout_scales_with_turnover():
    # hohes Volumen relativ zur Liquidität = mehr toxische Fills = höherer Markout-Verlust
    hi = rewards.markout_day(500, vol24=2_000_000, liquidity=100_000, markout_pp=4)
    lo = rewards.markout_day(500, vol24=50_000, liquidity=100_000, markout_pp=4)
    assert hi > lo > 0


def test_simulate_realistic_not_fantasy():
    # $2000 Pool, $500k Liquidität → Reward wenige $/Tag, KEINE 90.000%-Rendite
    s = rewards.simulate(pool=2000, vol24=250_000, liquidity=500_000, markout_pp=2.8)
    assert s["rewardDay"] < 5.0                 # nicht $1200
    assert s["netYieldPct"] < 2000              # keine absurde Rendite mehr
    assert "richness" in s and "sharePct" in s


def test_simulate_toxic_market_negative():
    # mickriger Pool, riesiges Volumen relativ zur Liquidität → netto negativ
    s = rewards.simulate(pool=6, vol24=5_000_000, liquidity=50_000, markout_pp=8)
    assert s["netDay"] < 0


def test_richness_ranks_fat_pool_thin_liquidity_higher():
    fat = rewards.simulate(pool=1000, vol24=100_000, liquidity=50_000, markout_pp=3)
    thin = rewards.simulate(pool=1000, vol24=100_000, liquidity=2_000_000, markout_pp=3)
    assert fat["richness"] > thin["richness"] and fat["rewardDay"] > thin["rewardDay"]


def test_daily_pool_from_clobrewards():
    m = {"clobRewards": [{"rewardsDailyRate": 1316}, {"rewardsDailyRate": 100}]}
    assert rewards._daily_pool(m) == 1416.0
    assert rewards._daily_pool({"rewardsDailyRate": 50}) == 50.0
    assert rewards._daily_pool({}) == 0.0
