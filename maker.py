#!/usr/bin/env python3
"""maker.py — Maker-Opportunity-Board (Vor-Live-Analyse) → docs/maker.json.

Der Clou aus den API-Daten: Taker zahlt Fee (~3,5pp am Geld), MAKER zahlt keine + kriegt Rebates
und Liquiditäts-Rewards (feeType crypto_fees_v2 takerOnly, rewardsMinSize/MaxSpread/DailyRate).
Statt den Spread zu überqueren, stellen wir Limit-Orders an unserer Deribit-Fair und lassen Taker
zu uns kommen: wir verdienen Spread + Rewards + sparen die Fee.

Ehrlich: das ist eine OPPORTUNITÄTS-Bewertung (wo wäre Making am attraktivsten?), KEINE Fill-
Simulation — echte Fills brauchen den Live-Orderbook-Feed (self-hosted Runner, Phase 4). READ-ONLY.

Kernzahl: als Maker reicht schon ein kleiner Puffer h, weil KEINE Fee anfällt; als Taker bräuchtest
du erst > ~3,5pp nur zum Breakeven. edgeIfFilledPP = h·100 (unser Vorteil je Fill an der Fair).
"""
from __future__ import annotations

import datetime
import json
import pathlib

MARKETS = pathlib.Path(__file__).parent / "docs" / "markets.json"
OUT = pathlib.Path(__file__).parent / "docs" / "maker.json"
TAKER_BREAKEVEN_PP = 3.5   # was ein Taker am Geld nur für die Fee bräuchte (Referenz fürs Framing)


def _load():
    try:
        return json.loads(MARKETS.read_text(encoding="utf-8")).get("markets", [])
    except Exception:
        return []


def board(markets=None):
    markets = markets if markets is not None else _load()
    out = []
    for m in markets:
        fair, poly = m.get("fairProb"), m.get("polyPrice")
        if fair is None or poly is None:
            continue
        bid, ask = m.get("bestBid"), m.get("bestAsk")
        spread_pp = round((ask - bid) * 100, 1) if (bid is not None and ask is not None) else None
        mid = (bid + ask) / 2 if (bid is not None and ask is not None) else poly
        max_spread = m.get("rewardsMaxSpread")
        liq = m.get("liquidityUSD") or 0
        reward_elig = bool(spread_pp is not None and max_spread and spread_pp <= max_spread
                           and liq >= (m.get("rewardsMinSize") or 0))
        # Vorschlags-Quotes um die Fair (halbe Spanne, gedeckelt).
        h = min((spread_pp or 4.0) / 200.0, 0.03)
        q_bid, q_ask = round(max(0.01, fair - h), 3), round(min(0.99, fair + h), 3)
        edge_if_filled_pp = round(h * 100, 1)
        score = round(edge_if_filled_pp + (2.0 if reward_elig else 0.0), 1)
        out.append({
            "market": m.get("market"), "family": m.get("family"), "conditionId": m.get("conditionId"),
            "fair": fair, "mid": round(mid, 3), "bid": bid, "ask": ask, "spreadPP": spread_pp,
            "quoteBid": q_bid, "quoteAsk": q_ask, "edgeIfFilledPP": edge_if_filled_pp,
            "rewardEligible": reward_elig, "liquidityUSD": liq, "isNew": m.get("isNew"),
            "score": score,
        })
    out.sort(key=lambda b: -b["score"])
    return out


def write():
    b = board()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(b), "rewardEligible": sum(1 for x in b if x["rewardEligible"]),
        "takerBreakevenPP": TAKER_BREAKEVEN_PP,
        "note": "Opportunitäts-Board (kein Live-Quoting). Als Maker keine Fee → schon kleiner Puffer +EV; "
                "als Taker erst > ~3,5pp. Reward-berechtigt = Spread ≤ maxSpread & Liq ≥ minSize.",
        "board": b[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Maker-Board: {len(b)} Märkte ({sum(1 for x in b if x['rewardEligible'])} reward-berechtigt)")


if __name__ == "__main__":
    write()
