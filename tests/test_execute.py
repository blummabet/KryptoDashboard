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


def test_dry_run_and_idempotent(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:A:t1", "side": "BUY", "conditionId": "A", "tokenId": "tok0",
         "usdc": 2.0, "label": "BTC über 70k", "priceHint": 0.4, "size": None}
    ]}))
    execute.run()
    lines = (tmp_path / "log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1 and "DRY_RUN" in lines[0]
    execute.run()                                   # zweiter Lauf auf denselben Intents
    assert len((tmp_path / "log.jsonl").read_text().strip().splitlines()) == 1   # kein Doppel


def test_kill_switch_blocks_execution(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYPTO_KILL_SWITCH", "1")
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:A:t1", "side": "BUY", "conditionId": "A", "tokenId": "tok0", "usdc": 2.0}
    ]}))
    execute.run()
    lines = (tmp_path / "log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1 and "REJECTED" in lines[0]


def test_skips_missing_token(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    (tmp_path / "intents.json").write_text(json.dumps({"intents": [
        {"id": "BUY:B:t1", "side": "BUY", "conditionId": "B", "tokenId": None, "usdc": 2.0}
    ]}))
    execute.run()
    assert not (tmp_path / "log.jsonl").exists()     # nichts platziert (kein tokenId)
