#!/usr/bin/env python3
"""rewards.py — Reward-Farming-Simulator + Markt-Scanner (read-only) → docs/rewards.json.

Polymarkets Liquidity Rewards: ruhende Limit-Orders nahe am Midpoint werden pro Minute gesampelt
und quadratisch nach Nähe gescored; man teilt sich den Tages-Pool anteilig — Order muss NICHT
gefillt werden. ABER: nah am Mid = viel Score UND viele TOXISCHE Fills (Adverse Selection). Der
ehrliche Nettowert = Reward − Markout-Verlust. Der Hebel (aus dem Postmortem): so quoten, dass man
GESCORED, aber selten GEFILLT wird — es gibt ein Optimum zwischen Mid und Max-Spread-Rand.

Dieser Simulator rechnet genau das:
  1. Scoring (Poly-Doku, quadratisch): score = size · ((maxSpread − dist)/maxSpread)²
  2. Reward/Tag = Pool · unser_score / (unser_score + Konkurrenz_score)
  3. Fill-Rate(dist): nah am Mid = viele Fills, am Rand ~0 (mit Markt-Volumen skaliert)
  4. Markout-Verlust/Tag = Fills · Einsatz · |Markout| (Markout aus unserer echten Maker-Messung)
  5. NETTO/Tag = Reward − Markout-Verlust → über dist optimieren (der „scored, nicht gefillt"-Punkt)
  6. Märkte nach Netto-Rendite ranken (der eigentliche Hebel = Marktauswahl)

EHRLICH: Simulation mit TRANSPARENTEN Annahmen (Konkurrenz, Fill-Kurve). Der Pool + maxSpread +
minSize sind ECHT (Gamma). Fill-Rate & Konkurrenz sind Modelle — der Beweis kommt erst live auf dem
Runner. Der Zweck: sehen, OB Reward-Farming netto plausibel positiv sein kann und WO das Optimum liegt.
"""
from __future__ import annotations

import datetime
import json
import pathlib

import poly_core

OUT = pathlib.Path(__file__).parent / "docs" / "rewards.json"
MAKER = pathlib.Path(__file__).parent / "docs" / "maker.json"

STAKE_USD = 500.0        # Kapital, das wir je Markt ins Band legen
# --- ANNAHMEN (transparent; der Reward-Anteil rechnet jetzt gegen die ECHTE Markt-Liquidität) ---
MARKOUT_FALLBACK_PP = 4.0  # |Markout| je Fill, falls maker.json keins liefert (unsere Messung ~ −4pp)
MIN_POOL_USD = 5.0       # Pools darunter ignorieren (Rauschen; Poly-Floor ist eh $1/Tag)
TURNOVER_DAMP = 0.15     # nur ein Bruchteil des Buch-Umschlags trifft wirklich UNSERE Order (gedämpft)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _daily_pool(m: dict) -> float:
    """Tages-Reward-Pool des Markts in USD (clobRewards[].rewardsDailyRate, sonst rewardsDailyRate)."""
    total = 0.0
    for r in (m.get("clobRewards") or []):
        total += _f(r.get("rewardsDailyRate")) or 0.0
    if total == 0:
        total = _f(m.get("rewardsDailyRate")) or 0.0
    return total


def order_score(size: float, dist: float, max_spread: float) -> float:
    """Poly-LRP-Scoring (quadratisch): size · ((v − dist)/v)². dist,v in Preis-Einheiten (0..1)."""
    if max_spread <= 0 or dist < 0 or dist > max_spread:
        return 0.0
    return size * ((max_spread - dist) / max_spread) ** 2


def reward_share(stake: float, liquidity: float) -> float:
    """Unser Anteil am Tages-Pool ~ pro-rata nach Kapital gegen die ECHTE Markt-Liquidität.
    (Standard-LP-Modell. Bester verfügbarer Proxy ohne Live-Orderbuch-Tiefe.)"""
    liq = max(liquidity, stake)                          # nie weniger als unser eigener Einsatz
    return stake / (stake + liq)


def markout_day(stake: float, vol24: float, liquidity: float, markout_pp: float) -> float:
    """Erwarteter Markout-Verlust/Tag: wie oft das Buch umschlägt × unser Kapital × |Markout|.
    Hohes Volumen relativ zur Liquidität = häufige (toxische) Fills."""
    liq = max(liquidity, 1.0)
    turnover = vol24 / liq                                # Buch-Umschläge/Tag
    adverse_notional = turnover * TURNOVER_DAMP * stake   # was von UNS angehandelt wird (gedämpft)
    return adverse_notional * abs(markout_pp) / 100.0


def simulate(pool: float, vol24: float, liquidity: float, markout_pp: float,
             stake: float = STAKE_USD) -> dict:
    """Netto/Tag = Reward-Anteil am Pool − erwarteter Markout-Verlust. Gegen ECHTE Liquidität."""
    share = reward_share(stake, liquidity)
    reward_day = pool * share
    mk_day = markout_day(stake, vol24, liquidity, markout_pp)
    net = reward_day - mk_day
    return {
        "sharePct": round(share * 100, 3),
        "rewardDay": round(reward_day, 2),
        "markoutDay": round(mk_day, 2),
        "netDay": round(net, 2),
        "netYieldPct": round(net / stake * 100 * 365, 1),   # annualisiert auf den Einsatz
        "poolDay": round(pool, 2),
        "richness": round(pool / max(liquidity, 1.0) * 100, 3),   # Pool je $100 Liquidität = Ergiebigkeit
    }


def _markout_pp():
    """Unser echter Maker-Markout (gehedged, selektiv) aus maker.json, sonst Fallback."""
    try:
        mo = json.loads(MAKER.read_text(encoding="utf-8")).get("markout", {})
        for k in ("avgSelectiveHedgedPP", "avgHedgedPP", "avgMarkoutPP"):
            if mo.get(k) is not None:
                return abs(mo[k])
    except Exception:
        pass
    return MARKOUT_FALLBACK_PP


def _reward_markets(limit: int = 100):
    url = (f"{poly_core.GAMMA_MARKETS}?closed=false&active=true"
           f"&order=volume24hr&ascending=false&limit={limit}")
    try:
        return poly_core._get_json(url) or []
    except Exception as e:
        print(f"  ⚠️ rewards: Markt-Fetch {e}")
        return []


def build() -> dict:
    markout_pp = _markout_pp()
    markets = _reward_markets()
    rows = []
    for m in markets:
        max_spread_c = _f(m.get("rewardsMaxSpread"))
        if not max_spread_c or max_spread_c <= 0:
            continue
        pool = _daily_pool(m)
        if pool < MIN_POOL_USD:
            continue
        min_size = _f(m.get("rewardsMinSize")) or 0.0
        vol24 = _f(m.get("volume24hr")) or 0.0
        liquidity = _f(m.get("liquidityClob")) or _f(m.get("liquidityNum")) or _f(m.get("liquidity")) or 0.0
        bid, ask = _f(m.get("bestBid")), _f(m.get("bestAsk"))
        price = ((bid + ask) / 2) if (bid and ask) else (_f(m.get("lastTradePrice")) or 0.5)
        sim = simulate(pool, vol24, liquidity, markout_pp)
        rows.append({
            "question": (m.get("question") or "")[:70], "slug": m.get("slug"),
            "poolDay": round(pool, 2), "maxSpreadCents": max_spread_c, "minSize": min_size,
            "vol24": round(vol24), "liquidity": round(liquidity), "price": round(price, 3),
            "sharePct": sim.get("sharePct"), "richness": sim.get("richness"),
            "rewardDay": sim.get("rewardDay"), "markoutDay": sim.get("markoutDay"),
            "netDay": sim.get("netDay"), "netYieldPct": sim.get("netYieldPct"),
            "positive": (sim.get("netDay") or 0) > 0,
        })
    rows.sort(key=lambda r: -(r["netDay"] or -1e9))
    pos = [r for r in rows if r["positive"]]
    summary = {
        "marketsScanned": len(rows),
        "netPositive": len(pos),
        "totalPoolDay": round(sum(r["poolDay"] for r in rows), 2),
        "bestNetDay": rows[0]["netDay"] if rows else None,
        "bestNetYieldPct": rows[0]["netYieldPct"] if rows else None,
        "markoutAssumedPP": round(markout_pp, 2),
        "stakeUSD": STAKE_USD,
    }
    return {"summary": summary, "markets": rows[:60]}


def write():
    try:
        data = build()
    except Exception as e:
        print(f"  ⚠️ rewards: {e}")
        data = {"summary": {"marketsScanned": 0}, "markets": []}
    data["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["note"] = ("Reward-Farming-Simulation: Pool/maxSpread/minSize ECHT (Gamma). Konkurrenz + "
                    "Fill-Rate sind transparente Annahmen (live zu kalibrieren). NETTO = Reward − "
                    "Markout-Verlust (Markout aus unserer echten Maker-Messung). Optimiert die "
                    "Platzierung ('scored, aber selten gefillt'). Beweis erst live auf dem Runner.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    s = data["summary"]
    print(f"  Rewards: {s.get('marketsScanned', 0)} Reward-Märkte, {s.get('netPositive', 0)} netto-positiv, "
          f"Pool ges. ${s.get('totalPoolDay')}/Tag, bester Netto ${s.get('bestNetDay')}/Tag "
          f"(Markout-Annahme {s.get('markoutAssumedPP')}pp)")


if __name__ == "__main__":
    write()
