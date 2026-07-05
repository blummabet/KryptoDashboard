import pmscan
from signals.whale_signal import WhaleFlowSignal, MAX_PP, MIN_WALLETS


def _sig(whale):
    return WhaleFlowSignal().evaluate({"whale": whale})


def test_cluster_buy_yes_positive():
    r = _sig({"uniqueWallets": 4, "yesNetUSD": 40000, "netFlowUSD": 40000, "dominantSide": "BUY"})
    assert not r.silent and r.adj_pp > 0 and r.adj_pp <= MAX_PP
    assert r.family == "flow"


def test_cluster_buy_no_is_bearish_for_yes():
    # 4 Wallets kaufen NO → yesNet negativ → Signal gegen Yes
    r = _sig({"uniqueWallets": 4, "yesNetUSD": -40000, "netFlowUSD": -40000, "dominantSide": "SELL"})
    assert not r.silent and r.adj_pp < 0


def test_below_min_wallets_silent():
    r = _sig({"uniqueWallets": MIN_WALLETS - 1, "yesNetUSD": 99999})
    assert r.silent


def test_no_data_silent():
    assert _sig(None).silent
    assert WhaleFlowSignal().evaluate({}).silent


def test_capped_at_max():
    r = _sig({"uniqueWallets": 20, "yesNetUSD": 5_000_000})
    assert abs(r.adj_pp) <= MAX_PP + 1e-9


def test_yes_signed_directions():
    assert pmscan._yes_signed("BUY", "Yes", 100) == 100
    assert pmscan._yes_signed("BUY", "No", 100) == -100
    assert pmscan._yes_signed("SELL", "Yes", 100) == -100
    assert pmscan._yes_signed("SELL", "No", 100) == 100
    assert pmscan._yes_signed("BUY", "Argentina", 100) == 0.0   # nicht-binär → 0


def test_market_whale_summary_parses_binary(monkeypatch):
    # market_whales-Schema (verifiziert): {trades, stats}. 3 Wallets kaufen NO → yesNet negativ.
    fake = {"market": {"slug": "x"}, "stats": {"total_trades": 3, "unique_wallets": 3,
            "buy_count": 3, "sell_count": 0, "total_volume_usd": 9000},
            "trades": [{"wallet": "0xa", "side": "BUY", "outcome": "No", "amount_usd": 3000},
                       {"wallet": "0xb", "side": "BUY", "outcome": "No", "amount_usd": 3000},
                       {"wallet": "0xc", "side": "BUY", "outcome": "No", "amount_usd": 3000}]}
    monkeypatch.setattr(pmscan, "market_whales", lambda *a, **k: fake)
    s = pmscan.market_whale_summary(slug="x")
    assert s["binary"] is True and s["uniqueWallets"] == 3
    assert s["yesNetUSD"] == -9000 and s["dominantSide"] == "SELL"


def test_market_whale_summary_multi_outcome(monkeypatch):
    fake = {"stats": {"unique_wallets": 2, "total_trades": 2},
            "trades": [{"wallet": "0xa", "side": "BUY", "outcome": "Brazil", "amount_usd": 5000},
                       {"wallet": "0xb", "side": "BUY", "outcome": "France", "amount_usd": 2000}]}
    monkeypatch.setattr(pmscan, "market_whales", lambda *a, **k: fake)
    s = pmscan.market_whale_summary(slug="wc")
    assert s["binary"] is False and s["yesNetUSD"] is None
    assert s["dominantOutcome"] == "Brazil"
