import fair_value as fv


def test_digital_atm_near_half():
    p = fv.digital_above(60000, 60000, 0.60, 1 / 365)
    assert 0.45 < p < 0.50  # leicht unter 0.5 wegen −0.5σ²t-Drift


def test_itm_and_otm():
    assert fv.digital_above(60000, 40000, 0.60, 1 / 365) > 0.99
    assert fv.digital_above(60000, 90000, 0.60, 1 / 365) < 0.02


def test_below_is_complement():
    a = fv.digital_above(60000, 55000, 0.6, 7 / 365)
    b = fv.digital_below(60000, 55000, 0.6, 7 / 365)
    assert abs(a + b - 1.0) < 1e-9


def test_bad_inputs_return_none():
    assert fv.digital_above(0, 1, 0.5, 1) is None
    assert fv.digital_above(1, 1, 0.0, 1) is None
    assert fv.digital_above(1, 1, 0.5, 0) is None


def test_edges_gross_net():
    assert fv.gross_edge_pp(0.53, 0.42) == 11.0
    assert fv.net_edge_pp(0.53, 0.42) < fv.gross_edge_pp(0.53, 0.42)  # Fee zieht ab
    assert fv.net_edge_pp(None, 0.42) is None


def test_fee_is_max_at_mid():
    assert fv.estimated_fee_pp(0.5) >= fv.estimated_fee_pp(0.1) >= fv.estimated_fee_pp(0.01)
    assert fv.estimated_fee_pp(None) == 0.0


def test_one_touch_bounds_and_none():
    assert fv.one_touch(60000, 70000, 0.6, 30 / 365) is not None
    assert 0.0 <= fv.one_touch(60000, 70000, 0.6, 30 / 365) <= 1.0
    assert fv.one_touch(60000, 70000, 0.0, 1) is None
    assert fv.one_touch(0, 70000, 0.6, 1) is None


def test_one_touch_closer_barrier_more_likely():
    near = fv.one_touch(60000, 62000, 0.6, 30 / 365)
    far = fv.one_touch(60000, 75000, 0.6, 30 / 365)
    assert near > far


def test_touch_ge_finish_above():
    # Wer am Ende drüber ist, hat die Barriere sicher berührt → Touch ≥ Digital-Above.
    s, k, iv, t = 60000, 68000, 0.6, 45 / 365
    assert fv.one_touch(s, k, iv, t) >= fv.digital_above(s, k, iv, t) - 1e-9


def test_one_touch_down_side():
    # Dip-Barriere unter Spot: näher = wahrscheinlicher.
    near = fv.one_touch(60000, 58000, 0.6, 30 / 365)
    far = fv.one_touch(60000, 45000, 0.6, 30 / 365)
    assert near > far >= 0.0
