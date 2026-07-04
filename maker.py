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
SIM = pathlib.Path(__file__).parent / "data" / "maker_sim.json"   # kumulierte Reward-Schätzung
TAKER_BREAKEVEN_PP = 3.5   # was ein Taker am Geld nur für die Fee bräuchte (Referenz fürs Framing)

# Reward-Schätzung (TRANSPARENTE ANNAHMEN — echte Zahlen erst mit dem Runner):
ASSUMED_SIZE_USD = 20.0    # angenommene Quote-Größe je Seite pro reward-berechtigtem Markt
REWARD_DAILY_YIELD = 0.003  # angenommene Reward-Rendite/Tag auf die Quote-Größe (0,3 % — Platzhalter)
RUNS_PER_DAY = 48          # 30-Min-Kadenz


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
        est_reward_day = round(ASSUMED_SIZE_USD * REWARD_DAILY_YIELD, 3) if reward_elig else 0.0
        score = round(edge_if_filled_pp + (2.0 if reward_elig else 0.0), 1)
        out.append({
            "market": m.get("market"), "family": m.get("family"), "conditionId": m.get("conditionId"),
            "fair": fair, "mid": round(mid, 3), "bid": bid, "ask": ask, "spreadPP": spread_pp,
            "quoteBid": q_bid, "quoteAsk": q_ask, "edgeIfFilledPP": edge_if_filled_pp,
            "rewardEligible": reward_elig, "estRewardDay": est_reward_day,
            "liquidityUSD": liq, "isNew": m.get("isNew"), "score": score,
        })
    out.sort(key=lambda b: -b["score"])
    return out


def write():
    b = board()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_elig = sum(1 for x in b if x["rewardEligible"])
    est_reward_day_total = round(sum(x["estRewardDay"] for x in b), 2)

    # Kumulierte Reward-Schätzung fortschreiben (zeitbasiert, wächst pro Lauf).
    sim = {"cumRewardEst": 0.0, "runs": 0}
    if SIM.exists():
        try:
            sim = json.loads(SIM.read_text(encoding="utf-8"))
        except Exception:
            pass
    sim["cumRewardEst"] = round(sim.get("cumRewardEst", 0.0) + est_reward_day_total / RUNS_PER_DAY, 4)
    sim["runs"] = sim.get("runs", 0) + 1
    sim["updatedAt"] = now
    SIM.parent.mkdir(parents=True, exist_ok=True)
    SIM.write_text(json.dumps(sim, indent=2, ensure_ascii=False))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": now, "count": len(b), "rewardEligible": n_elig,
        "takerBreakevenPP": TAKER_BREAKEVEN_PP,
        "sim": {
            "estRewardDayTotal": est_reward_day_total, "cumRewardEst": sim["cumRewardEst"],
            "runs": sim["runs"], "assumedSizeUSD": ASSUMED_SIZE_USD, "dailyYield": REWARD_DAILY_YIELD,
            "note": "Reward-Schätzung (zeitbasiert, GESCHÄTZT mit Annahme). Spread-Ertrag NICHT enthalten "
                    "— echte Fills + echte Rewards erst über den self-hosted Runner.",
        },
        "note": "Als Maker keine Fee → schon kleiner Puffer +EV; als Taker erst > ~3,5pp. "
                "Reward-berechtigt = Spread ≤ maxSpread & Liq ≥ minSize.",
        "board": b[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Maker-Board: {len(b)} Märkte, {n_elig} reward-berechtigt, "
          f"est ${est_reward_day_total}/Tag, kumuliert ${sim['cumRewardEst']}")


if __name__ == "__main__":
    write()
