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

# Reward-Schätzung (TRANSPARENTE ANNAHMEN — absolute Zahl erst am echten Payout kalibrierbar;
# die RICHTUNG stimmt aber: reward-berechtigt + anteils-gewichtet nach Konkurrenz):
ASSUMED_SIZE_USD = 50.0    # angenommene Quote-Größe je Seite (≥ typische rewardsMinSize=50)
REWARD_DAILY_YIELD = 0.003  # Basis-Yield/Tag auf unsere Größe bei GERINGER Konkurrenz
REF_COMPETITION = 5000.0   # Liq-Skala für den Anteils-Proxy: viel Liq = kleiner Anteil = weniger Reward
RUNS_PER_DAY = 24          # stündliche Kadenz
MAKER_HALF_SPREAD = 0.02   # angenommene Quote-Distanz zur Mitte (±2¢) für die Fill-Simulation


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
        min_size = m.get("rewardsMinSize") or 0
        liq = m.get("liquidityUSD") or 0
        # Eligibility KORREKT: Spread ≤ maxSpread UND unsere Quote-Größe ≥ rewardsMinSize
        # (rewardsMinSize ist die MIN-ORDER-Größe, NICHT die Markt-Liquidität — alter Bug).
        reward_elig = bool(spread_pp is not None and max_spread and spread_pp <= max_spread
                           and ASSUMED_SIZE_USD >= min_size)
        # Quotes um die MITTE zentrieren (dort maximiert das LRP den Score), Größe nach Fair schieben.
        h = min((spread_pp or 4.0) / 200.0, 0.03)
        q_bid, q_ask = round(max(0.01, mid - h), 3), round(min(0.99, mid + h), 3)
        skew = "bid" if fair > mid + 0.005 else ("ask" if fair < mid - 0.005 else "flat")
        # Vorteil je Fill an der günstigen Seite (vs. Fair).
        edge_if_filled_pp = round(max(fair - q_bid, q_ask - fair) * 100, 1)
        # Reward-Schätzung: anteils-gewichtet — viel Konkurrenz-Liq = kleiner Anteil = weniger Reward.
        share_mult = REF_COMPETITION / (REF_COMPETITION + liq) if liq else 1.0
        est_reward_day = round(ASSUMED_SIZE_USD * REWARD_DAILY_YIELD * share_mult, 4) if reward_elig else 0.0
        score = round(edge_if_filled_pp + est_reward_day * 100, 1)   # Reward-Anteil mit-gewichtet
        out.append({
            "market": m.get("market"), "family": m.get("family"), "conditionId": m.get("conditionId"),
            "fair": fair, "mid": round(mid, 3), "bid": bid, "ask": ask, "spreadPP": spread_pp,
            "quoteBid": q_bid, "quoteAsk": q_ask, "skew": skew, "edgeIfFilledPP": edge_if_filled_pp,
            "rewardEligible": reward_elig, "estRewardDay": est_reward_day,
            "rewardsDailyRate": m.get("rewardsDailyRate"), "shareMult": round(share_mult, 3),
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

    # ── Markout-Sim: pessimistische Fills (Preis handelt DURCH die Quote) ────────────────────
    # Wir hätten letzten Lauf um die MITTE quotiert (bid=prevMid−H, ask=prevMid+H). Ist der Preis
    # seither DURCH eine Quote gehandelt, gilt sie als gefüllt — und zwar genau dann, wenn sich der
    # Markt bewegt hat (= die toxische Richtung). Markout = Fill-Preis vs. der FAIR direkt danach:
    # negativ = Adverse Selection frisst Spread + Rewards. DIE Zahl, die über Phase 4 entscheidet.
    prev = sim.get("prevMids", {})
    new_prev, fills_this, mk_sum_this = {}, 0, 0.0
    for x in b:
        cid = x.get("conditionId")
        mid, fair = x.get("mid"), x.get("fair")
        if cid and mid is not None:
            new_prev[cid] = mid
        if not x["rewardEligible"] or mid is None or fair is None or cid not in prev:
            continue
        pm = prev[cid]
        pb, pa = pm - MAKER_HALF_SPREAD, pm + MAKER_HALF_SPREAD
        if mid <= pb:                    # Preis fiel durch unseren Bid → BUY @ pb
            mk = (fair - pb) * 100.0     # jetzt fair wert, gekauft für pb
            fills_this += 1; mk_sum_this += mk
        elif mid >= pa:                  # Preis stieg durch unseren Ask → SELL @ pa
            mk = (pa - fair) * 100.0
            fills_this += 1; mk_sum_this += mk
    sim["prevMids"] = new_prev
    sim["fills"] = sim.get("fills", 0) + fills_this
    sim["sumMarkoutPP"] = round(sim.get("sumMarkoutPP", 0.0) + mk_sum_this, 3)
    avg_markout = round(sim["sumMarkoutPP"] / sim["fills"], 2) if sim["fills"] else None

    SIM.parent.mkdir(parents=True, exist_ok=True)
    SIM.write_text(json.dumps(sim, indent=2, ensure_ascii=False))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": now, "count": len(b), "rewardEligible": n_elig,
        "takerBreakevenPP": TAKER_BREAKEVEN_PP,
        "sim": {
            "estRewardDayTotal": est_reward_day_total, "cumRewardEst": sim["cumRewardEst"],
            "runs": sim["runs"], "assumedSizeUSD": ASSUMED_SIZE_USD, "dailyYield": REWARD_DAILY_YIELD,
            "note": "Reward-Schätzung: anteils-gewichtet (Konkurrenz-Liq), Eligibility = Spread≤maxSpread "
                    "& Größe≥minSize, Quotes um die MITTE. Absolute Zahl unkalibriert (RICHTUNG stimmt: "
                    "dünn/neu = mehr). Spread-Ertrag NICHT enthalten — echte Fills+Rewards erst mit Runner.",
        },
        "markout": {
            "fills": sim["fills"], "avgMarkoutPP": avg_markout,
            "note": "DIE entscheidende Zahl: pessimistische Fills (Preis handelt DURCH die Quote), "
                    "Markout = Fill vs. Fair direkt nach dem Move. Negativ = Adverse Selection frisst "
                    "Spread + Rewards → dann braucht's Delta-Hedge. Grobe Stundenauflösung (echte 1/10-Min "
                    "erst mit Runner).",
        },
        "note": "Als Maker keine Fee → schon kleiner Puffer +EV; als Taker erst > ~3,5pp. "
                "Reward-berechtigt = Spread ≤ maxSpread & Liq ≥ minSize.",
        "board": b[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Maker-Board: {len(b)} Märkte, {n_elig} reward-berechtigt, "
          f"est ${est_reward_day_total}/Tag, kumuliert ${sim['cumRewardEst']}")


if __name__ == "__main__":
    write()
