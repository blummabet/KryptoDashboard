import guards
import pytest


def test_check_prob_ok():
    assert guards.check_prob(0.5) == 0.5
    assert guards.check_prob(None) is None


def test_check_prob_raises_out_of_range():
    with pytest.raises(guards.GuardError):
        guards.check_prob(1.5)
    with pytest.raises(guards.GuardError):
        guards.check_prob(float("nan"))


def test_check_row_clean():
    assert guards.check_row({"polyPrice": 0.5, "fairProb": 0.6, "strike": 100000,
                             "edgePP": 3.0, "ivPct": 45, "direction": "above"}) == []


def test_check_row_flags_problems():
    assert guards.check_row({"polyPrice": 2.0})
    assert guards.check_row({"polyPrice": 0.5, "fairProb": 1.4})
    assert guards.check_row({"polyPrice": 0.5, "strike": -1})
    assert guards.check_row({"polyPrice": 0.5, "edgePP": 250})
    assert guards.check_row({"polyPrice": 0.5, "direction": "sideways"})


def test_audit_and_reference():
    assert "x" in guards.audit_rows([{"slug": "x", "polyPrice": 2.0}])
    assert guards.check_reference(-1)
    assert guards.check_reference(60000, 0.5) == []
