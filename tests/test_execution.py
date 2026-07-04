import execution as ex
from execution import Order


def _wire(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "SPEND", tmp_path / "spend.json")
    monkeypatch.setattr(ex, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(ex, "KILL_FILE", tmp_path / "kill")
    monkeypatch.delenv("CRYPTO_KILL_SWITCH", raising=False)
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("CRYPTO_DAILY_USDC_CAP", "5")


def test_dry_run_places_and_cap_counts(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    assert ex.guarded_place(Order("BUY", "tok", 2.0, "BTC über 70k", "convergence"))["status"] == "DRY_RUN"
    assert ex.guarded_place(Order("BUY", "tok", 2.0))["status"] == "DRY_RUN"
    r3 = ex.guarded_place(Order("BUY", "tok", 2.0))         # 4+2 > 5 → Cap
    assert r3["status"] == "REJECTED" and "CAP" in r3["reason"]


def test_kill_switch_env_blocks(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYPTO_KILL_SWITCH", "1")
    r = ex.guarded_place(Order("BUY", "tok", 1.0))
    assert r["status"] == "REJECTED" and "kill" in r["reason"].lower()


def test_kill_switch_file_blocks(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    (tmp_path / "kill").write_text("")
    assert ex.guarded_place(Order("BUY", "tok", 1.0))["status"] == "REJECTED"


def test_live_without_balance_fails_safe(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("DRY_RUN", "0")
    r = ex.guarded_place(Order("BUY", "tok", 1.0))          # kein balance_reader
    assert r["status"] == "REJECTED" and "Balance" in r["reason"]


def test_live_reserve_floor_blocks(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("RESERVE_FLOOR_USDC", "100")
    monkeypatch.setenv("CRYPTO_DAILY_USDC_CAP", "1000")
    r = ex.guarded_place(Order("BUY", "tok", 1.0),
                         executor=ex.DryRunExecutor(), balance_reader=lambda: 100.5)
    assert r["status"] == "REJECTED" and "Reserve" in r["reason"]
