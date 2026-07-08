import analysis


def _closed(pnl, fee, stake=100, edge=3.0, side="YES", reason="converged", market="über $64,000 · x"):
    return {"status": "CLOSED", "realizedPnl": pnl, "feePaid": fee, "stakeUSD": stake,
            "entryEdgePP": edge, "side": side, "exitReason": reason, "market": market, "family": "above"}


def test_attribution_gross_minus_fee():
    # brutto = realized + fee; hier 2 Trades: +10(fee2), −4(fee3) → realized 6, fee 5, brutto 11
    a = analysis.attribution([_closed(10, 2), _closed(-4, 3)])
    assert a["realizedTotal"] == 6.0 and a["feesTotal"] == 5.0 and a["grossBeforeFees"] == 11.0
    assert a["nWin"] == 1 and a["nLoss"] == 1


def test_attribution_fee_eats_edge_flag():
    # Ø Fee (5/100*100=5pp) > Ø Edge (2pp) → feeEatsEdge True
    a = analysis.attribution([_closed(1, 5, edge=2.0), _closed(1, 5, edge=2.0)])
    assert a["avgFeePP"] == 5.0 and a["avgEntryEdgePP"] == 2.0 and a["feeEatsEdge"] is True


def test_attribution_entry_edge_uses_abs():
    # NO-Seite mit negativem entryEdgePP darf den Ø nicht ins Negative ziehen
    a = analysis.attribution([_closed(1, 1, edge=-4.0, side="NO"), _closed(1, 1, edge=4.0)])
    assert a["avgEntryEdgePP"] == 4.0


def test_exposure_bullish_bearish_classification():
    # über $X YES = bullish; über $X NO = bearish; dip $X YES = bearish; dip $X NO = bullish
    op = [
        {"status": "OPEN", "family": "above", "side": "YES", "market": "über $64,000 · x", "markPoly": 0.5, "stakeUSD": 100},
        {"status": "OPEN", "family": "above", "side": "NO", "market": "über $64,000 · x", "markPoly": 0.5, "stakeUSD": 100},
        {"status": "OPEN", "family": "touch", "side": "YES", "market": "dip $40,000 bis y", "markPoly": 0.5, "stakeUSD": 100},
        {"status": "OPEN", "family": "touch", "side": "NO", "market": "dip $40,000 bis y", "markPoly": 0.5, "stakeUSD": 100},
    ]
    e = analysis.btc_exposure(op)
    assert e["nLong"] == 2 and e["nShort"] == 2          # 1 above-YES + 1 dip-NO bullish; rest bearish
    assert e["netPct"] == 0.0 and e["concentrated"] is False


def test_exposure_one_sided_is_concentrated():
    op = [{"status": "OPEN", "family": "touch", "side": "YES", "market": "dip $40,000 bis y",
           "markPoly": 0.5, "stakeUSD": 100} for _ in range(5)]   # alle bearish
    e = analysis.btc_exposure(op)
    assert e["nShort"] == 5 and e["nLong"] == 0
    assert e["netPct"] == -100.0 and e["concentrated"] is True


def test_exposure_delta_proxy_weights_atm_more():
    # ein ATM (50¢) bullish + ein tiefes OTM (3¢) bearish → netto bullish (ATM wiegt mehr)
    op = [{"status": "OPEN", "family": "above", "side": "YES", "market": "über $64,000 · x", "markPoly": 0.5, "stakeUSD": 100},
          {"status": "OPEN", "family": "above", "side": "NO", "market": "über $64,000 · x", "markPoly": 0.03, "stakeUSD": 100}]
    e = analysis.btc_exposure(op)
    assert e["netWeighted"] > 0 and e["netPct"] > 0
