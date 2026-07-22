import rewards


def test_order_score_quadratic_and_zero_outside_band():
    v = 0.03
    # am Mid (dist 0) = voller Score = size; am Rand (dist=v) = 0
    assert abs(rewards.order_score(100, 0.0, v) - 100) < 1e-9
    assert rewards.order_score(100, v, v) == 0.0
    # quadratisch: halbe Distanz → (0.5)² = 0.25 · size
    assert abs(rewards.order_score(100, v / 2, v) - 25.0) < 1e-9
    # außerhalb des Bands → 0
    assert rewards.order_score(100, v * 1.5, v) == 0.0


def test_fill_rate_falls_with_distance():
    v = 0.03
    near = rewards.fill_rate_per_day(0.0, v, 100000)
    far = rewards.fill_rate_per_day(v, v, 100000)
    mid = rewards.fill_rate_per_day(v / 2, v, 100000)
    assert near > mid > far and abs(far) < 1e-9


def test_fill_rate_scales_with_volume():
    v = 0.03
    assert rewards.fill_rate_per_day(0.005, v, 200000) > rewards.fill_rate_per_day(0.005, v, 20000)


def test_simulate_returns_best_placement():
    # Ruhiger Markt (wenig Volumen), fetter Pool → NETTO sollte positiv sein, Optimum abseits vom Mid
    s = rewards.simulate(pool=500, max_spread=0.03, min_size=50, vol24=20000, price=0.5, markout_pp=4.0)
    assert s["netDay"] > 0
    assert 0 <= s["distCents"] <= 3.0
    assert "netYieldPct" in s


def test_simulate_toxic_market_can_go_negative():
    # Riesiges Volumen (viele toxische Fills), mickriger Pool → NETTO negativ
    s = rewards.simulate(pool=5, max_spread=0.03, min_size=50, vol24=5_000_000, price=0.5, markout_pp=8.0)
    assert s["netDay"] < 0


def test_daily_pool_from_clobrewards():
    m = {"clobRewards": [{"rewardsDailyRate": 1316}, {"rewardsDailyRate": 100}]}
    assert rewards._daily_pool(m) == 1416.0
    assert rewards._daily_pool({"rewardsDailyRate": 50}) == 50.0
    assert rewards._daily_pool({}) == 0.0


def test_optimizer_picks_the_net_maximum():
    # Der zurückgegebene Punkt muss das NETTO-Maximum über die Platzierung sein (Optimierer korrekt).
    pool, v, ms, vol, pr, mk = 200, 0.04, 50, 300000, 0.5, 6.0
    best = rewards.simulate(pool, v, ms, vol, pr, mk)
    our = max(rewards.STAKE_USD / pr, ms)
    # Netto an ein paar Stützstellen selbst nachrechnen und gegen best prüfen
    def net_at(dist):
        osc = rewards.order_score(our, dist, v)
        comp = rewards.order_score(rewards.COMP_SHARES, v * 0.5, v)
        rew = pool * osc / (osc + comp) if osc + comp else 0
        fills = rewards.fill_rate_per_day(dist, v, vol)
        return rew - fills * rewards.STAKE_USD * mk / 100
    grid = [net_at(v * i / 24) for i in range(25)]
    assert abs(best["netDay"] - max(grid)) < 0.5    # best = das Maximum
