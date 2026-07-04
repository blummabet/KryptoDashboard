#!/usr/bin/env python3
"""data_sources.py — Referenz- und Kontext-Datenquellen (live geprüft, nie angenommen).

Verifiziert 2026-07-03:
  · Deribit index price: /public/get_index_price?index_name=btc_usd → result.index_price  ✅
  · Deribit expiries:    /public/get_expirations?currency=BTC&kind=option
                          → result.btc.option = ["4JUL26","5JUL26",…,"31JUL26",…]           ✅
  · Deribit IV am Strike:/public/ticker?instrument_name=BTC-10JUL26-60000-C
                          → result.mark_iv (in %!), result.underlying_price (Forward)         ✅
  · Binance /api/v3/ticker/price lieferte LEER → ⚠️ im Actions-Runner verifizieren
    (Binance blockt oft US-IPs; GitHub-Runner sind meist US-basiert). Fallback data-api.binance.vision
    oder über den self-hosted Runner ziehen.

Fair Value rechnet auf dem Deribit-Forward + Smile-IV (selbst-konsistent, sharp).
Binance-Spot wird nur als Auflösungs-Sanity angezeigt (Basis zu Deribit ist klein, aber real).
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.request

_H = {"User-Agent": "CryptoEdge/1.0", "Accept": "application/json"}
_DERIBIT = "https://www.deribit.com/api/v2/public"
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_EXP_CACHE: dict[str, list[str]] = {}


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers=_H)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── Referenz-Spot ────────────────────────────────────────────────────────────────────────────
def binance_spot(symbol="BTCUSDT"):
    """Auflösungs-identischer Spot. Kann von US-Runnern geblockt sein → Fallback-Host + None."""
    for host in ("api.binance.com", "data-api.binance.vision"):
        try:
            d = _get(f"https://{host}/api/v3/ticker/price?symbol={symbol}")
            if d and d.get("price"):
                return float(d["price"])
        except Exception as e:
            print(f"  ⚠️ binance_spot via {host}: {e}")
    return None


def deribit_index(currency="BTC"):
    """Composite-Indexpreis von Deribit (nah an Binance, ≠ identisch = Basis-Risiko)."""
    try:
        d = _get(f"{_DERIBIT}/get_index_price?index_name={currency.lower()}_usd")
        return float(d["result"]["index_price"])
    except Exception as e:
        print(f"  ⚠️ deribit_index({currency}): {e}")
        return None


# ── Deribit-Optionen: IV am Strike/Verfall (das Herz des Fair Value) ───────────────────────────
def deribit_expirations(currency="BTC"):
    key = currency.upper()
    if key not in _EXP_CACHE:
        d = _get(f"{_DERIBIT}/get_expirations?currency={key}&kind=option")
        _EXP_CACHE[key] = d["result"][key.lower()]["option"]
    return _EXP_CACHE[key]


def _exp_to_date(code: str):
    m = re.match(r"(\d{1,2})([A-Z]{3})(\d{2})$", code.upper())
    if not m or m.group(2) not in _MONTHS:
        return None
    return datetime.date(2000 + int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))


def nearest_expiry(target_date: datetime.date, currency="BTC"):
    """Deribit-Verfall am nächsten zum Zieldatum (bevorzugt ≥ Zieldatum)."""
    dated = [(c, _exp_to_date(c)) for c in deribit_expirations(currency)]
    dated = [x for x in dated if x[1]]
    if not dated:
        return None
    ge = [x for x in dated if x[1] >= target_date]
    pool = ge or dated
    return min(pool, key=lambda x: abs((x[1] - target_date).days))[0]


_TICKER_CACHE: dict[str, dict | None] = {}  # pro Lauf dedupen (viele Märkte teilen Strike/Verfall)


def _option_iv(strike: int, expiry_code: str, currency="BTC"):
    name = f"{currency.upper()}-{expiry_code}-{int(round(strike))}-C"
    if name not in _TICKER_CACHE:
        try:
            d = _get(f"{_DERIBIT}/ticker?instrument_name={name}")
            r = d.get("result") or {}
            iv = r.get("mark_iv")
            if iv is None:
                _TICKER_CACHE[name] = None
            else:
                fwd = r.get("underlying_price") or r.get("index_price")
                _TICKER_CACHE[name] = {"iv": iv / 100.0, "forward": float(fwd),
                                       "strike": int(round(strike)), "expiry": expiry_code}
        except Exception:
            _TICKER_CACHE[name] = None  # Instrument existiert nicht / Fehler
    return _TICKER_CACHE[name]


def _iv_at_strike(strike, expiry_code, currency="BTC"):
    """IV+Forward am Strike für einen Verfall; snappt auf die nächste gelistete Strike-Stufe."""
    seen = set()
    for k in [int(strike)] + [int(round(strike / s) * s) for s in (1000, 2000, 5000, 10000)]:
        if k <= 0 or k in seen:
            continue
        seen.add(k)
        got = _option_iv(k, expiry_code, currency)
        if got:
            return got
    return None


def _years_to(d: datetime.date):
    """Jahre von jetzt bis 08:00 UTC am Datum d (Deribit-Verfallszeit)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    tgt = datetime.datetime(d.year, d.month, d.day, 8, 0, tzinfo=datetime.timezone.utc)
    return max((tgt - now).total_seconds(), 0.0) / (365.0 * 24 * 3600)


def deribit_fair_inputs(strike, target_date: datetime.date, currency="BTC"):
    """IV (dez.) + Forward für Strike/Zieldatum. Interpoliert zwischen den beiden Deribit-Verfällen,
    die das Zieldatum einrahmen (Varianz-linear in der Zeit → korrekte Term-Struktur; Forward linear).
    Snappt Strikes auf gelistete Stufen. None wenn nichts Brauchbares (→ fairProb bleibt leer)."""
    try:
        dated = sorted([(c, _exp_to_date(c)) for c in deribit_expirations(currency) if _exp_to_date(c)],
                       key=lambda x: x[1])
    except Exception as e:
        print(f"  ⚠️ deribit expirations: {e}")
        return None
    if not dated:
        return None

    lower = [x for x in dated if x[1] <= target_date]
    upper = [x for x in dated if x[1] >= target_date]
    lo = lower[-1] if lower else None
    up = upper[0] if upper else None

    # Exakter Treffer oder nur eine Seite verfügbar → ein Verfall (nächster).
    if lo and up and lo[0] == up[0]:
        got = _iv_at_strike(strike, lo[0], currency)
        return {**got, "expiry": lo[0]} if got else None
    if not lo or not up:
        e = up or lo
        got = _iv_at_strike(strike, e[0], currency)
        return {**got, "expiry": e[0]} if got else None

    # Beidseitig → in Varianz interpolieren.
    g_lo = _iv_at_strike(strike, lo[0], currency)
    g_up = _iv_at_strike(strike, up[0], currency)
    if not g_lo or not g_up:
        g = g_lo or g_up
        return {**g, "expiry": (lo[0] if g_lo else up[0])} if g else None

    t_lo, t_up, t_t = _years_to(lo[1]), _years_to(up[1]), _years_to(target_date)
    if not (0 < t_lo < t_up) or t_t <= 0:
        return {**g_up, "expiry": up[0]}
    w = (t_t - t_lo) / (t_up - t_lo)
    var_lo, var_up = g_lo["iv"] ** 2 * t_lo, g_up["iv"] ** 2 * t_up
    var_t = var_lo + (var_up - var_lo) * w
    iv_t = (var_t / t_t) ** 0.5 if var_t > 0 else g_up["iv"]
    fwd_t = g_lo["forward"] + (g_up["forward"] - g_lo["forward"]) * w
    return {"iv": iv_t, "forward": fwd_t, "strike": g_up["strike"], "expiry": f"{lo[0]}→{up[0]}"}


# ── Kontext-Seams: erst live prüfen, dann verdrahten (Lucas hat die Zugänge) ───────────────────
def etf_net_flow(asset="BTC"):
    """TODO: ETF-Netto-Flow (Farside/SoSoValue). EOD-verzögert → NUR Kontext/Regime, nie Trigger."""
    return None


def fear_greed():
    """Crypto Fear & Greed Index (alternative.me). Regime-Kontext, gedämpft — NIE Trade-Trigger.
    Shape (stabil): {"data":[{"value":"28","value_classification":"Fear","timestamp":"…"}]}.
    Defensiv geparst; erster Actions-Lauf bestätigt die Struktur live."""
    try:
        d = _get("https://api.alternative.me/fng/?limit=1", timeout=8)
        item = (d.get("data") or [{}])[0]
        v = item.get("value")
        return {"value": int(v) if v is not None else None,
                "classification": item.get("value_classification")}
    except Exception as e:
        print(f"  ⚠️ fear_greed: {e}")
        return None


def funding_rate(symbol="BTCUSDT"):
    """TODO: Perp-Funding (Positionierung). Schnelles Kontext-Signal."""
    return None


if __name__ == "__main__":
    # Smoke gegen die echte API (nur mit Netz).
    print("expiries:", deribit_expirations("BTC")[:6])
    fi = deribit_fair_inputs(60000, datetime.date.today() + datetime.timedelta(days=7))
    print("fair inputs @60k/+7d:", fi)
