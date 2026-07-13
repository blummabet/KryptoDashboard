import datetime

import whales


def _prof(**kw):
    base = {"wins": 60, "losses": 40, "unique_markets": 50, "roi": 12.0, "total_pnl": 50000.0,
            "win_rate": 60.0, "total_volume": 400000.0, "biggest_win_usd": 5000.0,
            "last_trade_date": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    base.update(kw)
    return base


def test_good_wallet_qualifies():
    v = whales.judge(_prof())
    assert v["qualified"] is True and v["rejectReasons"] == []
    assert v["resolved"] == 100


def test_one_hit_wonder_rejected():
    # Trump-Wal-Muster: fast der ganze Gewinn aus EINEM Trade
    v = whales.judge(_prof(total_pnl=22_000_000.0, biggest_win_usd=8_300_000.0 * 2))
    assert v["oneHit"] is True and v["qualified"] is False
    assert any("Ein-Treffer" in r for r in v["rejectReasons"])


def test_losing_whale_rejected():
    # aktiver Wal, gute Trefferquote, aber ROI negativ → raus
    v = whales.judge(_prof(roi=-0.91, total_pnl=-103151.0, win_rate=54.9))
    assert v["qualified"] is False
    assert any("verliert Geld" in r for r in v["rejectReasons"])


def test_inactive_rejected():
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=400)).isoformat()
    v = whales.judge(_prof(last_trade_date=old))
    assert v["qualified"] is False
    assert any("inaktiv" in r for r in v["rejectReasons"])


def test_small_sample_rejected():
    v = whales.judge(_prof(wins=18, losses=4, unique_markets=23))
    assert v["qualified"] is False
    assert any("zu wenig Historie" in r for r in v["rejectReasons"])


def test_copy_lag_buy_yes_costs_when_price_rose():
    # Wal kauft Yes @ 0.50, jetzt 0.58 → Kopieren kostet +8pp
    t = {"side": "BUY", "outcome": "Yes", "price": 0.50}
    assert whales._copy_lag_pp(t, 0.58) == 8.0


def test_copy_lag_buy_no_mirrors_price():
    # Wal kauft NO @ 0.40 (=Yes 0.60). Yes steht jetzt 0.55 → No jetzt 0.45 → kostet +5pp
    t = {"side": "BUY", "outcome": "No", "price": 0.40}
    assert whales._copy_lag_pp(t, 0.55) == 5.0


def test_copy_lag_sell_direction_flips():
    # Wal VERKAUFT Yes @ 0.60, jetzt nur noch 0.55 → wir verkaufen schlechter → +5pp Kosten
    t = {"side": "SELL", "outcome": "Yes", "price": 0.60}
    assert whales._copy_lag_pp(t, 0.55) == 5.0


def test_copy_lag_none_without_price():
    assert whales._copy_lag_pp({"side": "BUY", "outcome": "Yes", "price": 0.5}, None) is None
