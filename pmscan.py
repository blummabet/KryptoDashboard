#!/usr/bin/env python3
"""pmscan.py — Isolierter PolymarketScan-API-Client (freie Whale-/Smart-Money-Daten).

Read-only. Liefert Whale-Flow pro Markt als KONTEXT (weiche Quelle → nie ein blinder Trade-Trigger,
nur ein kalibriertes Kontext-Signal; siehe WhaleFlowSignal). Key aus env POLYMARKETSCAN_API_KEY.
OHNE Key oder bei Fetch-Fehler: still None zurück (Pipeline läuft weiter, Signal bleibt silent).

Basis-URL + Endpoints verifiziert 2026-07-05 (polymarketscan.org/api, frei, 30 Req/Min).
Roh-Whale-Daten stecken letztlich in Polymarkets eigener Trade-API + On-Chain → langfristig
selbst ziehen statt Dritt-Anbieter-Abhängigkeit.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api"
_HEADERS = {"User-Agent": "CryptoEdge/1.0", "Accept": "application/json"}


def api_key() -> str | None:
    k = os.environ.get("POLYMARKETSCAN_API_KEY", "").strip()
    return k or None


def _get(endpoint: str, params: dict, timeout: int = 12):
    """GET auf die public-api. None wenn kein Key, Fehler oder Rate-Limit."""
    key = api_key()
    if not key:
        return None
    q = {"endpoint": endpoint, "api_key": key, **{k: v for k, v in params.items() if v is not None}}
    url = f"{BASE}?{urllib.parse.urlencode(q)}"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"  ⚠️ pmscan {endpoint}: {e}")
        return None
    if isinstance(data, dict) and data.get("error"):
        print(f"  ⚠️ pmscan {endpoint}: {data.get('error')}")
        return None
    return data.get("data") if isinstance(data, dict) else data


def market_whales(slug: str | None = None, market_id: str | None = None,
                  min_size: int = 1000, limit: int = 100) -> dict | None:
    """Whale-Daten EINES Markts. Schema (verifiziert 2026-07-05):
       {market:{...}, trades:[{wallet, side, outcome, amount_usd, price, tier, ...}], stats:{...}}."""
    d = _get("market_whales", {"market_slug": slug, "market_id": market_id,
                               "min_size": min_size, "limit": limit})
    return d if isinstance(d, dict) else None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _trade_fields(t: dict):
    """Feld-Extraktion (market_whales: amount_usd; whale_trades: size)."""
    side = (t.get("side") or t.get("action") or "").upper()
    usd = _num(t.get("amount_usd") or t.get("size") or t.get("usd") or t.get("notional"))
    outcome = (t.get("outcome") or t.get("outcome_name") or "").strip()
    wallet = t.get("wallet") or t.get("proxy") or t.get("address")
    return side, usd, outcome, wallet


def _yes_signed(side: str, outcome: str, usd: float) -> float:
    """Vorzeichen Richtung YES (binärer Markt): BUY Yes / SELL No = +, BUY No / SELL Yes = −.
    Bei nicht-binären Outcomes (Kandidatenname) nicht anwendbar → 0."""
    o = outcome.lower()
    if o not in ("yes", "no"):
        return 0.0
    is_yes = (o == "yes")
    if side == "BUY":
        return usd if is_yes else -usd
    if side == "SELL":
        return -usd if is_yes else usd
    return 0.0


def market_whale_summary(slug: str | None = None, market_id: str | None = None,
                         min_size: int = 1000) -> dict | None:
    """Aggregiertes Whale-Bild EINES Markts (Kontext-Signal-Futter):
      uniqueWallets, nTrades, buy/sellCount (aus stats), totalVolumeUSD,
      yesNetUSD (Netto Richtung YES, nach Outcome vorzeichenkorrigiert — für binäre Märkte),
      netFlowUSD (=yesNet bei binär, sonst BUY−SELL grob), dominantOutcome (bei Multi-Outcome).
    None ohne Key/Daten. Hinweis: win_rate ist hier nicht enthalten → informierte Gewichtung
    bräuchte separate wallet_profile-Calls (später; Rate-Limit-schonend)."""
    data = market_whales(slug, market_id, min_size=min_size)
    if not data:
        return None
    trades = data.get("trades") or []
    stats = data.get("stats") or {}
    if not trades:
        return None
    wallets = set()
    yes_net = 0.0
    buy = sell = 0.0
    per_outcome: dict[str, float] = {}
    binary = True
    for t in trades:
        side, usd, outcome, wallet = _trade_fields(t)
        if usd is None:
            continue
        if wallet:
            wallets.add(str(wallet).lower())
        if side == "BUY":
            buy += usd
        elif side == "SELL":
            sell += usd
        if outcome.lower() not in ("yes", "no"):
            binary = False
            per_outcome[outcome] = per_outcome.get(outcome, 0.0) + (usd if side == "BUY" else -usd)
        yes_net += _yes_signed(side, outcome, usd)
    net = yes_net if binary else (buy - sell)
    dom_outcome = max(per_outcome, key=lambda k: per_outcome[k]) if per_outcome else None
    return {
        "yesNetUSD": round(yes_net, 2) if binary else None,
        "netFlowUSD": round(net, 2),
        "buyUSD": round(buy, 2), "sellUSD": round(sell, 2),
        "nTrades": int(stats.get("total_trades") or len(trades)),
        "uniqueWallets": int(stats.get("unique_wallets") or len(wallets)),
        "buyCount": stats.get("buy_count"), "sellCount": stats.get("sell_count"),
        "totalVolumeUSD": _num(stats.get("total_volume_usd")),
        "binary": binary,
        "dominantSide": "BUY" if net > 0 else ("SELL" if net < 0 else "FLAT"),
        "dominantOutcome": dom_outcome,
    }


def leaderboard(limit: int = 50) -> list | None:
    d = _get("leaderboard", {"limit": limit})
    return d if isinstance(d, list) else (d.get("traders") if isinstance(d, dict) else None)


if __name__ == "__main__":
    import sys
    if not api_key():
        print("Kein POLYMARKETSCAN_API_KEY gesetzt → Client bleibt still (read-only).")
    else:
        s = sys.argv[1] if len(sys.argv) > 1 else "will-bitcoin-hit-100k"
        print(json.dumps(market_whale_summary(slug=s), indent=2))
