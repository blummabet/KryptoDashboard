import json

import execute
import execution


def _wire(tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(execution, "SPEND", tmp_path / "spend.json")
    monkeypatch.setattr(execution, "KILL_FILE", tmp_path / "kill")
    monkeypatch.setattr(execute, "INTENTS", tmp_path / "intents.json")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("CRYPTO_DAILY_USDC_CAP", "1000")
    monkeypatch.delenv("CRYPTO_KILL_SWITCH", raising=False)


def _order_lines(p):
    """Log-Zeilen ohne die Lauf-Zusammenfassung (type='run')."""
    if not p.exists():
        return []
    out = []
    for line in p.read_text().strip().splitlines():
        rec = json.loads(line)
        if rec.get("type") != "run":
            out.append(rec)
    return out


def test_dry_run_and_idempotent(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:A:t1", "side": "BUY", "conditionId": "A", "tokenId": "tok0",
         "usdc": 2.0, "label": "BTC über 70k", "priceHint": 0.4, "size": None}
    ]}))
    execute.run()
    ol = _order_lines(tmp_path / "log.jsonl")
    assert len(ol) == 1 and ol[0]["status"] == "DRY_RUN"
    execute.run()                                   # zweiter Lauf auf denselben Intents
    assert len(_order_lines(tmp_path / "log.jsonl")) == 1   # kein Doppel


def test_kill_switch_blocks_execution(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYPTO_KILL_SWITCH", "1")
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:A:t1", "side": "BUY", "conditionId": "A", "tokenId": "tok0", "usdc": 2.0}
    ]}))
    execute.run()
    ol = _order_lines(tmp_path / "log.jsonl")
    assert len(ol) == 1 and ol[0]["status"] == "REJECTED"


def test_skips_missing_token(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:B:t1", "side": "BUY", "conditionId": "B", "tokenId": None, "usdc": 2.0}
    ]}))
    execute.run()
    assert _order_lines(tmp_path / "log.jsonl") == []     # nichts platziert (kein tokenId)
