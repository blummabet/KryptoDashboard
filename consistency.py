#!/usr/bin/env python3
"""consistency.py — Cross-Market-No-Arbitrage-Scanner (modell-frei) → docs/arb.json.

Poly widerspricht sich oft SELBST auf demselben Underlying/Datum. Diese Widersprüche sind ohne
jeden externen Anker erkennbar = die schärfste, modell-unabhängige Kante. READ-ONLY, misst nur.

Geprüfte Regel — Monotonie der Strike-Leiter je (family, Datum, Richtung):
  · above / touch-up : P(über/erreicht K) muss mit steigendem K FALLEN.
  · touch-down (dip) : P(dip auf K) muss mit steigendem K STEIGEN (näher am Spot = wahrscheinlicher).
Jede Inversion benachbarter Strikes ist ein risikoarmer Arb (billige Seite kaufen, teure verkaufen).
gapPP = Widerspruch in Prozentpunkten; erst über ~2×Taker-Fee wirklich handelbar.
"""
from __future__ import annotations

import datetime
import json
import pathlib

MARKETS = pathlib.Path(__file__).parent / "docs" / "markets.json"
OUT = pathlib.Path(__file__).parent / "docs" / "arb.json"
FEE_2X_PP = 7.0   # grober Handelbar-Schwellwert (2× Taker-Fee am Geld); darunter = reines Signal


def _load():
    try:
        return json.loads(MARKETS.read_text(encoding="utf-8")).get("markets", [])
    except Exception:
        return []


def scan(markets=None):
    markets = markets if markets is not None else _load()
    groups = {}
    for m in markets:
        if m.get("polyPrice") is None or m.get("strike") is None:
            continue
        key = (m.get("family"), (m.get("endDate") or "")[:10], m.get("direction"))
        groups.setdefault(key, []).append(m)

    findings = []
    for (family, date, direction), rows in groups.items():
        rows = sorted(rows, key=lambda r: r["strike"])
        expect_down = not (family == "touch" and direction == "below")  # dip = steigend, sonst fallend
        for a, b in zip(rows, rows[1:]):
            pa, pb = a["polyPrice"], b["polyPrice"]
            inverted = (pb > pa) if expect_down else (pb < pa)
            if inverted and a["strike"] != b["strike"]:
                gap = round(abs(pb - pa) * 100, 2)
                findings.append({
                    "family": family, "date": date, "direction": direction,
                    "lowStrike": a["strike"], "highStrike": b["strike"],
                    "lowP": pa, "highP": pb, "lowCid": a.get("conditionId"), "highCid": b.get("conditionId"),
                    "lowBid": a.get("bestBid"), "lowAsk": a.get("bestAsk"),
                    "highBid": b.get("bestBid"), "highAsk": b.get("bestAsk"),
                    "gapPP": gap, "tradable": gap >= FEE_2X_PP,
                    "note": f"{a['market']} ({pa:.0%}) ↔ {b['market']} ({pb:.0%}) verletzt Monotonie",
                })
    findings.sort(key=lambda f: -f["gapPP"])
    return findings


def _yes_ask(m):
    """Ausführbarer Kaufpreis für Yes (bestAsk), Fallback polyPrice. None wenn beides fehlt."""
    a = m.get("bestAsk")
    return a if a is not None else m.get("polyPrice")


def _yes_bid(m):
    """Ausführbarer Verkaufspreis für Yes (bestBid), Fallback polyPrice. None wenn beides fehlt."""
    b = m.get("bestBid")
    return b if b is not None else m.get("polyPrice")


def scan_negrisk(markets=None):
    """NegRisk-Basket-Arb (modell-frei, exklusiv-erschöpfend): bei einem Event mit negRisk=True
    zahlt am Ende GENAU ein Yes-Outcome $1, alle anderen $0. Also muss Σ Yes = 1 sein.
      · Σ bestAsk(Yes) < 1  → alle Yes kaufen: Einstand < $1, sicherer Payout $1 → Gap risikofrei.
      · Σ bestBid(Yes) > 1  → alle Yes verkaufen: Einnahme > $1, Auszahlung genau $1 → Gap risikofrei.
    READ-ONLY. Bleibt leer, solange Poly Krypto nur verschachtelte Leitern (negRisk=false) listet.
    """
    markets = markets if markets is not None else _load()
    groups = {}
    for m in markets:
        if not m.get("negRisk") or not m.get("eventId"):
            continue
        if m.get("polyPrice") is None:
            continue
        groups.setdefault(m["eventId"], []).append(m)

    findings = []
    for eid, rows in groups.items():
        if len(rows) < 2:
            continue                       # ein einzelnes Outcome ist kein Basket
        asks = [_yes_ask(m) for m in rows]
        bids = [_yes_bid(m) for m in rows]
        if any(a is None for a in asks) or any(b is None for b in bids):
            continue
        buy_cost = sum(asks)               # alle Yes am Ask kaufen
        sell_credit = sum(bids)            # alle Yes am Bid verkaufen
        title = rows[0].get("eventTitle") or str(eid)
        legs = [{"market": m.get("market"), "cid": m.get("conditionId"),
                 "ask": m.get("bestAsk"), "bid": m.get("bestBid"),
                 "clobTokenIds": m.get("clobTokenIds")} for m in rows]
        if buy_cost < 1.0:
            gap = round((1.0 - buy_cost) * 100, 2)
            findings.append({"type": "negrisk_basket", "side": "buy", "eventId": eid,
                             "event": title, "n": len(rows), "basketCost": round(buy_cost, 4),
                             "gapPP": gap, "tradable": gap >= FEE_2X_PP, "legs": legs,
                             "note": f"{title}: Σ Yes-Ask={buy_cost:.3f} < 1 → Basket kaufen ({gap:.1f}pp)"})
        elif sell_credit > 1.0:
            gap = round((sell_credit - 1.0) * 100, 2)
            findings.append({"type": "negrisk_basket", "side": "sell", "eventId": eid,
                             "event": title, "n": len(rows), "basketCredit": round(sell_credit, 4),
                             "gapPP": gap, "tradable": gap >= FEE_2X_PP, "legs": legs,
                             "note": f"{title}: Σ Yes-Bid={sell_credit:.3f} > 1 → Basket verkaufen ({gap:.1f}pp)"})
    findings.sort(key=lambda f: -f["gapPP"])
    return findings


def write():
    findings = scan()
    baskets = scan_negrisk()
    tradable = sum(1 for f in findings if f["tradable"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(findings), "tradableCount": tradable,
        "note": "Monotonie-Verletzungen in Polys eigener Strike-Leiter (modell-frei). tradable = Gap ≥ ~2× Fee.",
        "findings": findings[:60],
        "basketFindings": baskets[:40],
        "basketCount": len(baskets),
        "basketTradable": sum(1 for f in baskets if f["tradable"]),
    }, indent=2, ensure_ascii=False))
    print(f"  Konsistenz: {len(findings)} Widersprüche ({tradable} handelbar), "
          f"{len(baskets)} NegRisk-Baskets")


if __name__ == "__main__":
    write()
