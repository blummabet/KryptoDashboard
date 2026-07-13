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

import fair_value

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

# Hedge-KOSTEN auf Binance-Spot (pro Seite; Hin+Zurück = ×2). Der Delta-Hedge ist nicht gratis —
# ohne diese Kosten ist jede "gehedged positiv"-Zahl geschönt.
HEDGE_FEE_MAKER = 0.0002   # 0,02 %/Seite — Hedge als Limit-Order (günstig, aber Ausführung unsicher)
HEDGE_FEE_TAKER = 0.0010   # 0,10 %/Seite — Hedge sofort per Market-Order (sicher, teurer)


# Selektivität: wo Making Sinn ergibt (adverse Selektion kleiner). Nicht am Rand (unsichere Fair),
# nicht kurz vor Auflösung (Intraday-Toxizität), genug Liquidität.
SELECT_MIN_LIQ = 3000.0
SELECT_MIN_DAYS = 1.0
SELECT_MID_LO, SELECT_MID_HI = 0.08, 0.92


def _load():
    try:
        return json.loads(MARKETS.read_text(encoding="utf-8")).get("markets", [])
    except Exception:
        return []


def _delta(m: dict, spot):
    """BTC-Delta der Position: ∂fairProb/∂Spot (numerisch, in Wkt.-Punkten pro $ Spot).
    Für den Delta-Hedge: wie stark bewegt sich unsere faire Wkt., wenn BTC 1$ macht?"""
    strike, ivp, days = m.get("strike"), m.get("ivPct"), m.get("daysLeft")
    fam, direction = m.get("family"), m.get("direction")
    if strike is None or ivp is None or days is None or spot is None or days <= 0:
        return None
    iv, T, ds = ivp / 100.0, days / 365.0, max(spot * 0.001, 1.0)

    def f(s):
        if fam == "touch":
            return fair_value.one_touch(s, strike, iv, T)
        return (fair_value.digital_above(s, strike, iv, T) if direction != "below"
                else fair_value.digital_below(s, strike, iv, T))

    a, b = f(spot + ds), f(spot - ds)
    if a is None or b is None:
        return None
    return (a - b) / (2 * ds)   # Wkt. pro $ Spot


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
        spot = m.get("spot")
        delta = _delta(m, spot)
        days = m.get("daysLeft")
        # Selektiv = wo Making tragfähig sein sollte (adverse Selektion kleiner + hedgebar).
        maker_select = bool(reward_elig and liq >= SELECT_MIN_LIQ
                            and SELECT_MID_LO <= mid <= SELECT_MID_HI
                            and (days is None or days >= SELECT_MIN_DAYS)
                            and delta is not None)
        out.append({
            "market": m.get("market"), "family": m.get("family"), "conditionId": m.get("conditionId"),
            "fair": fair, "mid": round(mid, 3), "bid": bid, "ask": ask, "spreadPP": spread_pp,
            "quoteBid": q_bid, "quoteAsk": q_ask, "skew": skew, "edgeIfFilledPP": edge_if_filled_pp,
            "rewardEligible": reward_elig, "estRewardDay": est_reward_day,
            "rewardsDailyRate": m.get("rewardsDailyRate"), "shareMult": round(share_mult, 3),
            "liquidityUSD": liq, "isNew": m.get("isNew"), "score": score,
            "spot": spot, "delta": round(delta, 6) if delta is not None else None,
            "makerSelect": maker_select,
        })
    out.sort(key=lambda b: -b["score"])
    return out


def markout_step(board_rows, prev_mids, prev_spot, pending=None, half=MAKER_HALF_SPREAD):
    """Ein Markout-Schritt (testbar, ohne I/O), in ZWEI Phasen.

    ⚠️ KORREKTUR (2026-07-13): Markout wird jetzt gegen den KÜNFTIGEN MARKT-MID gemessen, NICHT
    mehr gegen unsere Fair — die ist nachweislich schlechter kalibriert als der Marktpreis
    (Brier 0,111 vs 0,096), ein Markout dagegen wäre wertlos. Das ist der Standard im Market-Making.

    Wichtig: der Fill wird von einer Mid-Bewegung ausgelöst — bewertet man ihn gegen DENSELBEN Mid,
    ist er per Konstruktion immer negativ (zirkulär). Deshalb:
      Phase 1: offene Fills vom LETZTEN Lauf gegen den JETZIGEN Mid bewerten (echter Vorwärts-Markout).
      Phase 2: neue Fills erkennen (Mid handelt durch die Quote vom letzten Lauf) → in die Warteschlange.
    Hedge: Spot-getriebenen Teil per Delta rausrechnen; Hedge-Notional je Fill mitschreiben, damit
    Hedge-KOSTEN später realistisch abgezogen werden können.
    """
    pending = pending or []
    spot_now = next((x.get("spot") for x in board_rows if x.get("spot") is not None), None)
    by_cid = {x["conditionId"]: x for x in board_rows if x.get("conditionId")}

    # ── Phase 1: offene Fills gegen den jetzigen Markt-Mid bewerten ──────────────────────────
    fills = sel_fills = 0
    raw = hedged = sel_hedged = hedge_notional = 0.0
    for f in pending:
        x = by_cid.get(f.get("cid"))
        if not x or x.get("mid") is None:
            continue                      # Markt weg/aufgelöst → Fill verfällt
        mid_now = x["mid"]
        fp, side = f.get("fillPrice"), f.get("side")
        if fp is None or side not in ("BUY", "SELL"):
            continue
        mk = (mid_now - fp) * 100.0 if side == "BUY" else (fp - mid_now) * 100.0
        dspot = ((spot_now - f["spotAtFill"]) if (spot_now is not None and f.get("spotAtFill") is not None) else 0.0)
        hedge_pp = (f.get("delta") or 0.0) * dspot * 100.0
        mk_h = mk - hedge_pp if side == "BUY" else mk + hedge_pp
        fills += 1
        raw += mk
        hedged += mk_h
        hedge_notional += f.get("hedgeNotionalUSD") or 0.0
        if f.get("select"):
            sel_fills += 1
            sel_hedged += mk_h

    # ── Phase 2: neue Fills erkennen (Quote vom letzten Lauf) → Warteschlange ────────────────
    new_pending, new_prev = [], {}
    for x in board_rows:
        cid, mid = x.get("conditionId"), x.get("mid")
        if cid and mid is not None:
            new_prev[cid] = mid
        if not x.get("rewardEligible") or mid is None or cid not in prev_mids:
            continue
        pm = prev_mids[cid]
        pb, pa = pm - half, pm + half
        if mid <= pb:
            side, fp = "BUY", pb
        elif mid >= pa:
            side, fp = "SELL", pa
        else:
            continue
        delta = x.get("delta") or 0.0
        shares = ASSUMED_SIZE_USD / max(fp, 0.01)
        hn = abs(shares * delta * (spot_now or 0.0))   # zu hedgendes Spot-Notional in USD
        new_pending.append({"cid": cid, "side": side, "fillPrice": round(fp, 4),
                            "spotAtFill": spot_now, "delta": delta,
                            "select": bool(x.get("makerSelect")), "hedgeNotionalUSD": round(hn, 2)})

    return {"spotNow": spot_now, "newPrev": new_prev, "newPending": new_pending,
            "fills": fills, "rawSum": round(raw, 3), "hedgedSum": round(hedged, 3),
            "selFills": sel_fills, "selHedgedSum": round(sel_hedged, 3),
            "hedgeNotionalUSD": round(hedge_notional, 2)}


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
    # Einmaliger Reset auf gemeinsame Stichprobe: roh & gehedged müssen über DIESELBEN Fills laufen,
    # sonst ist der Vergleich unfair (roh hatte Historie, gehedged fing bei 0 an). markoutV=2 markiert
    # die neue Ära; die alte −5,7pp-Baseline ist dokumentiert.
    # markoutV=3: Benchmark gewechselt (Markt-Mid statt unserer Fair) → alte Zahlen unvergleichbar.
    if sim.get("markoutV") != 3:
        sim["fills"] = 0
        sim["sumMarkoutPP"] = 0.0
        sim["sumHedgedPP"] = 0.0
        sim["selFills"] = 0
        sim["sumSelHedgedPP"] = 0.0
        sim["sumHedgeNotionalUSD"] = 0.0
        sim["pendingFills"] = []
        sim["markoutV"] = 3

    step = markout_step(b, sim.get("prevMids", {}), sim.get("prevSpot"), sim.get("pendingFills", []))
    sim["prevMids"] = step["newPrev"]
    sim["prevSpot"] = step["spotNow"]
    sim["pendingFills"] = step["newPending"]
    sim["fills"] = sim.get("fills", 0) + step["fills"]
    sim["sumMarkoutPP"] = round(sim.get("sumMarkoutPP", 0.0) + step["rawSum"], 3)
    sim["sumHedgedPP"] = round(sim.get("sumHedgedPP", 0.0) + step["hedgedSum"], 3)
    sim["selFills"] = sim.get("selFills", 0) + step["selFills"]
    sim["sumSelHedgedPP"] = round(sim.get("sumSelHedgedPP", 0.0) + step["selHedgedSum"], 3)
    sim["sumHedgeNotionalUSD"] = round(sim.get("sumHedgeNotionalUSD", 0.0) + step["hedgeNotionalUSD"], 2)

    n = sim["fills"]
    avg_markout = round(sim["sumMarkoutPP"] / n, 2) if n else None
    avg_hedged = round(sim["sumHedgedPP"] / n, 2) if n else None
    avg_sel_hedged = round(sim["sumSelHedgedPP"] / sim["selFills"], 2) if sim["selFills"] else None

    # Hedge-KOSTEN: Notional × Satz × 2 (auf + zu), umgerechnet in pp je Position.
    def _cost_pp(rate):
        if not n:
            return None
        return round(sim["sumHedgeNotionalUSD"] * rate * 2 / (n * ASSUMED_SIZE_USD) * 100, 2)

    cost_maker, cost_taker = _cost_pp(HEDGE_FEE_MAKER), _cost_pp(HEDGE_FEE_TAKER)
    net_of = lambda v, c: (round(v - c, 2) if (v is not None and c is not None) else None)
    net_maker = net_of(avg_sel_hedged if avg_sel_hedged is not None else avg_hedged, cost_maker)
    net_taker = net_of(avg_sel_hedged if avg_sel_hedged is not None else avg_hedged, cost_taker)

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
            "avgHedgedPP": avg_hedged, "avgSelectiveHedgedPP": avg_sel_hedged,
            "selFills": sim.get("selFills", 0),
            "hedgeCostMakerPP": cost_maker, "hedgeCostTakerPP": cost_taker,
            "netMakerHedgePP": net_maker, "netTakerHedgePP": net_taker,
            "benchmark": "künftiger Markt-Mid (NICHT unsere Fair)",
            "note": "Markout gegen den KÜNFTIGEN MARKT-MID (Standard im Market-Making) — nicht mehr gegen "
                    "unsere Fair, die nachweislich schlechter kalibriert ist als der Markt. Fill wird im "
                    "Folgelauf bewertet (sonst zirkulär). ROH negativ = Adverse Selection. GEHEDGED = "
                    "Spot-getriebener Teil per Delta rausgerechnet. NETTO = minus echte Hedge-Kosten "
                    "(Binance, Hin+Zurück). Erst NETTO entscheidet, ob Making trägt.",
        },
        "note": "Als Maker keine Fee → schon kleiner Puffer +EV; als Taker erst > ~3,5pp. "
                "Reward-berechtigt = Spread ≤ maxSpread & Liq ≥ minSize.",
        "board": b[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Maker-Board: {len(b)} Märkte, {n_elig} reward-berechtigt, est ${est_reward_day_total}/Tag | "
          f"Markout(vs Markt-Mid) roh {avg_markout} / gehedged {avg_hedged} / selektiv {avg_sel_hedged} "
          f"| Hedge-Kosten {cost_maker}/{cost_taker}pp → NETTO {net_maker} (maker) / {net_taker} (taker) "
          f"| {sim['fills']} Fills, {len(sim.get('pendingFills', []))} pending")


if __name__ == "__main__":
    write()
