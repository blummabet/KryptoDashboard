import json

import arb_engine as ae


def _m(cid, strike, poly):
    return {"conditionId": cid, "market": f"über ${strike} · 2026-07-31", "strike": strike,
            "polyPrice": poly, "family": "above", "direction": "above",
            "endDate": "2026-07-31T16:00:00Z"}


def _wire(tmp_path, monkeypatch, markets, res=None):
    monkeypatch.setattr(ae, "POSITIONS", tmp_path / "arb.json")
    monkeypatch.setattr(ae, "OUT", tmp_path / "arbout.json")
    monkeypatch.setattr(ae, "_load_markets", lambda: markets)
    monkeypatch.setattr(ae.resolutions, "load_resolutions", lambda: (res or {}))


def test_arb_opens_on_inversion(tmp_path, monkeypatch):
    # "über 60k" @30% billiger als "über 64k" @45% → unmöglich → Gap 15pp, handelbar
    _wire(tmp_path, monkeypatch, [_m("L", 60000, 0.30), _m("H", 64000, 0.45)])
    ae.run()
    pos = json.loads((tmp_path / "arb.json").read_text())
    assert len(pos) == 1 and pos[0]["status"] == "OPEN"
    assert pos[0]["supersetCid"] == "L" and pos[0]["subsetCid"] == "H"   # billige Seite = Superset
    assert pos[0]["gapPP"] == 15.0 and pos[0]["lockedMin"] > 0


def test_arb_settles_positive_mid(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_m("L", 60000, 0.30), _m("H", 64000, 0.45)])
    ae.run()
    # Preis endet zwischen 60k und 64k → über60k=1, über64k=0 → payoff 2 (Bonus)
    _wire(tmp_path, monkeypatch, [], res={"L": {"outcome": 1}, "H": {"outcome": 0}})
    ae.run()
    pos = json.loads((tmp_path / "arb.json").read_text())
    assert pos[0]["status"] == "CLOSED" and pos[0]["realizedPnl"] > 0


def test_arb_worst_case_still_locks_gap(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_m("L", 60000, 0.30), _m("H", 64000, 0.45)])
    ae.run()
    # Preis endet über beiden → payoff 1 = Minimum; trotzdem Gewinn = gesperrter Gap
    _wire(tmp_path, monkeypatch, [], res={"L": {"outcome": 1}, "H": {"outcome": 1}})
    ae.run()
    pos = json.loads((tmp_path / "arb.json").read_text())
    assert pos[0]["realizedPnl"] > 0


def test_arb_no_open_when_consistent(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_m("L", 60000, 0.80), _m("H", 64000, 0.55)])
    ae.run()
    assert json.loads((tmp_path / "arb.json").read_text()) == []
