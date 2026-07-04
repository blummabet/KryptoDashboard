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
