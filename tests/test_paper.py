import json

import paper_engine as pe


def _mkt(cid, edge, poly=0.40, fair=0.45, liq=50000, family="above"):
    return {"conditionId": cid, "slug": cid, "market": "BTC " + cid, "family": family,
            "polyPrice": poly, "fairProb": fair, "edgePP": edge, "edgeGrossPP": edge,
            "liquidityUSD": liq}


def _wire(tmp_path, monkeypatch, markets, res=None):
    monkeypatch.setattr(pe, "POSITIONS", tmp_path / "pos.json")
    monkeypatch.setattr(pe, "OUT", tmp_path / "paper.json")
    monkeypatch.setattr(pe, "_load_markets", lambda: markets)
    monkeypatch.setattr(pe.resolutions, "load_resolutions", lambda: (res or {}))


def test_open_position(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_mkt("A", 5.0)])
    pe.run()
    pos = json.loads((tmp_path / "pos.json").read_text())
    assert len(pos) == 1 and pos[0]["side"] == "YES" and pos[0]["status"] == "OPEN"
    view = json.loads((tmp_path / "paper.json").read_text())
    assert view["summary"]["openCount"] == 1


def test_side_and_gates(tmp_path, monkeypatch):
    # Edge −5 → NO öffnen; Edge +1 unter Floor → nein; hoher Edge aber Liq zu klein → nein.
    _wire(tmp_path, monkeypatch, [_mkt("N", -5.0, poly=0.60), _mkt("S", 1.0), _mkt("L", 5.0, liq=100)])
    pe.run()
    pos = json.loads((tmp_path / "pos.json").read_text())
    assert len(pos) == 1 and pos[0]["conditionId"] == "N" and pos[0]["side"] == "NO"


def test_converge_close_profit(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_mkt("A", 5.0, poly=0.40)])
    pe.run()                                   # YES @ 0.40
    # Edge geschlossen + Poly auf 0.45 gestiegen → converged, Gewinn
    monkeypatch.setattr(pe, "_load_markets", lambda: [_mkt("A", 0.2, poly=0.45)])
    pe.run()
    pos = json.loads((tmp_path / "pos.json").read_text())
    assert pos[0]["status"] == "CLOSED" and pos[0]["exitReason"] == "converged"
    assert pos[0]["realizedPnl"] > 0


def test_thesis_break(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_mkt("A", 5.0, poly=0.40)])
    pe.run()
    monkeypatch.setattr(pe, "_load_markets", lambda: [_mkt("A", -6.0, poly=0.34)])
    pe.run()
    pos = json.loads((tmp_path / "pos.json").read_text())
    assert pos[0]["exitReason"] == "thesis_break" and pos[0]["realizedPnl"] < 0


def test_resolution_settlement(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, [_mkt("A", 5.0, poly=0.40)])
    pe.run()                                   # YES @ 0.40
    # Markt verschwindet + löst als Yes auf → resolved_win, PnL > 0
    _wire(tmp_path, monkeypatch, [], res={"A": {"outcome": 1}})
    pe.run()
    pos = json.loads((tmp_path / "pos.json").read_text())
    assert pos[0]["status"] == "CLOSED" and pos[0]["exitReason"] == "resolved_win"
    assert pos[0]["realizedPnl"] > 0
