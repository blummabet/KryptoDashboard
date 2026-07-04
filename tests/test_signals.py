from signals.base import Signal, SignalResult
from signals.context_signals import FearGreedSignal
from signals.registry import SignalRegistry, combine


def test_fear_greed_active():
    r = FearGreedSignal().evaluate({"context": {"fearGreed": {"value": 20, "classification": "Fear"}}})
    assert not r.silent and r.adj_pp > 0 and r.family == "sentiment"


def test_fear_greed_silent_when_missing():
    assert FearGreedSignal().evaluate({"context": {}}).silent


def test_registry_guard_on_exception():
    class Boom(Signal):
        name, family = "boom", "x"
        def evaluate(self, ctx):
            raise ValueError("kaputt")
    reg = SignalRegistry()
    reg.register(Boom())
    res = reg.evaluate_all({})
    assert res[0].silent and "guard" in res[0].evidence


def test_combine_anticorrelation():
    rs = [SignalResult("iv", "vola", 2.0), SignalResult("rv", "vola", 1.0),
          SignalResult("fund", "flow", 1.5)]
    out = combine(rs)
    # vola: 2.0 voll + 1.0*0.4 gedämpft = 2.4 ; flow 1.5 → 3.9
    assert abs(out["engine_adj_pp"] - 3.9) < 1e-9
    assert 0 <= out["conviction"] <= 10
    assert out["families"] == 2
