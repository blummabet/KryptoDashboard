#!/usr/bin/env python3
"""whales.py — Whale-Follow-Tracker (read-only) → docs/whales.json.

Die EHRLICHE Version von Copy-Trading. Copy-Trading-Seiten (Polystreet & Co.) zeigen nur PnL und
nur die Gewinner. Das ist Survivorship Bias. Wir prüfen selbst nach:

  1. BILANZ SELBST RECHNEN: ROI, Trefferquote, Anzahl Märkte, letzte Aktivität — nicht dem
     Leaderboard glauben. (Der #1 dort ist der Trump-Wal von 2024: $22M, aber nur 23 Märkte und
     seit 11/2024 inaktiv. Und ein aktiver Wal mit 30k Trades + 55% Trefferquote macht ROI −0,9%.)
  2. HART FILTERN: Ein-Treffer-Wunder, Inaktive, Verlierer und Kleinst-Stichproben fliegen raus.
  3. COPY-LAG MESSEN: die Zahl, die keine Copy-Seite ausweist. Wenn der Wal kauft, bewegt SEINE
     Order den Preis. Wir kopieren danach und zahlen schlechter. copyLagPP = aktueller Poly-Preis
     − Wal-Preis, in SEINE Richtung. Frisst der Lag die Kante, ist Copy-Trading tot — egal wie gut
     der Wal ist.

READ-ONLY, kein echtes Geld. Braucht POLYMARKETSCAN_API_KEY (sonst still).
"""
from __future__ import annotations

import datetime
import json
import pathlib
import time

import pmscan
import poly_core

OUT = pathlib.Path(__file__).parent / "docs" / "whales.json"

FEED_LIMIT = 100         # Live-Feed Großtrades (breiter ziehen, um echte Whale-Größen zu erwischen)
MAX_WALLET_PROBES = 14   # Rate-Limit (30 Req/Min)
LEADER_N = 12            # Top-Trader vom Leaderboard (bewiesene Groß-Wallets) mit-prüfen
WHALE_MIN_USD = 25000    # ERST ab hier ein echter Wal (nicht $1k-„Fisch"). PolymarketScan: $50k = Whale.
SLEEP = 2.1

# Glaubwürdigkeits-Schwellen (bewusst hart — wir wollen keine Glückspilze kopieren)
MIN_RESOLVED = 50        # wins+losses: darunter ist alles Rauschen
MIN_UNIQUE_MARKETS = 20  # sonst Ein-Themen-Zocker
MAX_INACTIVE_DAYS = 45   # tote Wale nützen nichts
ONE_HIT_SHARE = 0.50     # ein Trade > 50% des ganzen Gewinns = Ein-Treffer-Wunder


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _days_since(iso: str | None):
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return round((_now() - dt).total_seconds() / 86400, 1)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def judge(p: dict) -> dict:
    """Unser EIGENES Urteil über eine Wallet — nicht das Leaderboard-Marketing."""
    wins, losses = int(p.get("wins") or 0), int(p.get("losses") or 0)
    resolved = wins + losses
    roi = _f(p.get("roi"))
    pnl = _f(p.get("total_pnl")) or 0.0
    uniq = int(p.get("unique_markets") or 0)
    inactive = _days_since(p.get("last_trade_date"))
    big_win = _f(p.get("biggest_win_usd")) or 0.0
    one_hit = bool(pnl > 0 and big_win > 0 and (big_win / pnl) > ONE_HIT_SHARE)

    reasons = []
    if resolved < MIN_RESOLVED:
        reasons.append(f"zu wenig Historie ({resolved} aufgelöst)")
    if uniq < MIN_UNIQUE_MARKETS:
        reasons.append(f"nur {uniq} Märkte")
    if one_hit:
        reasons.append(f"Ein-Treffer-Wunder ({big_win/pnl:.0%} des Gewinns aus 1 Trade)")
    if inactive is not None and inactive > MAX_INACTIVE_DAYS:
        reasons.append(f"inaktiv seit {inactive:.0f}d")
    if roi is not None and roi <= 0:
        reasons.append(f"verliert Geld (ROI {roi:.1f}%)")
    if pnl <= 0:
        reasons.append("negatives PnL")

    return {
        "resolved": resolved, "uniqueMarkets": uniq, "roi": round(roi, 2) if roi is not None else None,
        "pnl": round(pnl, 2), "winRate": round(_f(p.get("win_rate")) or 0, 1),
        "volume": round(_f(p.get("total_volume")) or 0, 0),
        "inactiveDays": inactive, "oneHit": one_hit,
        "biggestWin": round(big_win, 2),
        "qualified": not reasons,
        "rejectReasons": reasons,
    }


def _poly_price_now(slug: str):
    """Aktueller Yes-Preis des Markts (für die Copy-Lag-Messung)."""
    m = poly_core.fetch_market(slug)
    if not m:
        return None
    try:
        return float(json.loads(m.get("outcomePrices") or "[]")[0])
    except Exception:
        return None


def _copy_lag_pp(trade: dict, now_price: float | None):
    """Was uns das Kopieren KOSTET, in pp — in die Richtung des Wals.
    Er kauft Outcome @ p, jetzt steht es bei q → wir zahlen (q − p) mehr. Positiv = teurer für uns."""
    p = _f(trade.get("price"))
    if p is None or now_price is None:
        return None
    side = (trade.get("side") or "").upper()
    # now_price ist der YES-Preis. Kaufte er "No", ist sein Preis auf der No-Seite → spiegeln.
    oc = (trade.get("outcome") or "").strip().lower()
    q = now_price if oc != "no" else (1.0 - now_price)
    lag = (q - p) if side == "BUY" else (p - q)
    return round(lag * 100, 2)


def build() -> dict:
    if not pmscan.api_key():
        print("  ⚠️ whales: kein POLYMARKETSCAN_API_KEY → leerer Stand")
        return {"enabled": False, "wallets": [], "feed": [], "summary": {}}

    feed = pmscan.whale_trades(limit=FEED_LIMIT) or []
    big_trades = [t for t in feed if (_f(t.get("size")) or 0) >= WHALE_MIN_USD]  # ECHTE Whale-Größe

    # Kandidaten = (a) bewiesene Groß-Wallets vom Leaderboard + (b) Wallets mit echtem Whale-Trade
    # im Feed. NICHT mehr die aktivsten Klein-Trader (das waren HF-Grinder, keine Wale).
    lb = pmscan.leaderboard(limit=LEADER_N) or []
    time.sleep(SLEEP)
    candidates, seen = [], set()
    for t in lb:                                   # Leaderboard zuerst (bewiesen groß)
        w = t.get("wallet_address") or t.get("wallet")
        if w and w not in seen:
            seen.add(w); candidates.append(w)
    for t in sorted(big_trades, key=lambda t: -(_f(t.get("size")) or 0)):
        w = t.get("wallet")
        if w and w not in seen:
            seen.add(w); candidates.append(w)
    candidates = candidates[:MAX_WALLET_PROBES]
    biggest = max((_f(t.get("size")) or 0) for t in feed) if feed else 0

    wallets = []
    for w in candidates:
        prof = pmscan.wallet_profile(w)
        time.sleep(SLEEP)
        if not prof:
            continue
        v = judge(prof)
        v.update({"wallet": w, "name": prof.get("display_name") or w[:10] + "…",
                  "firstTrade": (prof.get("first_trade_date") or "")[:10],
                  "lastTrade": (prof.get("last_trade_date") or "")[:10]})
        wallets.append(v)
    wallets.sort(key=lambda x: (not x["qualified"], -(x["roi"] or -999)))

    qual = {w["wallet"] for w in wallets if w["qualified"]}

    # Copy-Lag NUR für ECHTE Whale-Trades (≥ WHALE_MIN) qualifizierter Wale messen.
    rows, lags = [], []
    seen_slug: dict[str, float | None] = {}
    # Feed nach Größe sortiert zeigen (die dicksten oben), damit man echte Wale sieht.
    for t in sorted(feed, key=lambda t: -(_f(t.get("size")) or 0)):
        w = t.get("wallet")
        size = _f(t.get("size")) or 0
        is_q = w in qual
        is_whale = size >= WHALE_MIN_USD
        slug = t.get("market")
        lag = None
        if is_q and is_whale and slug:                  # Lag nur auf echten Whale-Fills
            if slug not in seen_slug:
                seen_slug[slug] = _poly_price_now(slug)
            lag = _copy_lag_pp(t, seen_slug[slug])
            if lag is not None:
                lags.append(lag)
        rows.append({
            "wallet": w, "name": (w or "")[:10] + "…", "qualified": is_q, "isWhale": is_whale,
            "market": t.get("market_question") or slug, "slug": slug,
            "side": t.get("side"), "outcome": t.get("outcome"),
            "price": _f(t.get("price")), "sizeUSD": size,
            "ts": t.get("timestamp"), "copyLagPP": lag,
        })

    avg_lag = round(sum(lags) / len(lags), 2) if lags else None
    summary = {
        "enabled": True,
        "feedCount": len(feed),
        "whaleTradeCount": len(big_trades),
        "biggestTradeUSD": round(biggest),
        "whaleMinUSD": WHALE_MIN_USD,
        "walletsProbed": len(wallets),
        "qualifiedCount": len(qual),
        "rejectedCount": len(wallets) - len(qual),
        "avgCopyLagPP": avg_lag,
        "lagSample": len(lags),
        "verdict": ("Kopieren kostet im Schnitt %.2fpp pro echtem Whale-Trade" % avg_lag) if avg_lag is not None
                   else ("keine ≥$%dk-Whale-Trades qualifizierter Wale im Fenster — echte Wale sind selten"
                         % (WHALE_MIN_USD // 1000)),
    }
    return {"summary": summary, "wallets": wallets, "feed": rows[:60]}


def write():
    try:
        data = build()
    except Exception as e:
        print(f"  ⚠️ whales: {e}")
        data = {"summary": {"enabled": False}, "wallets": [], "feed": []}
    data["generatedAt"] = _now().strftime("%Y-%m-%d %H:%M UTC")
    data["note"] = ("Ehrliches Copy-Trading: Bilanz selbst nachgerechnet (nicht dem Leaderboard glauben), "
                    "Ein-Treffer-Wunder/Inaktive/Verlierer gefiltert, und der Copy-Lag ausgewiesen — "
                    "die Kosten, die entstehen, weil der Wal mit seiner Order den Preis selbst bewegt.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    s = data.get("summary", {})
    print(f"  Whales: {s.get('walletsProbed', 0)} geprüft, {s.get('qualifiedCount', 0)} qualifiziert, "
          f"Ø Copy-Lag {s.get('avgCopyLagPP')}pp")


if __name__ == "__main__":
    write()
