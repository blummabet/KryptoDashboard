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
                    "gapPP": gap, "tradable": gap >= FEE_2X_PP,
                    "note": f"{a['market']} ({pa:.0%}) ↔ {b['market']} ({pb:.0%}) verletzt Monotonie",
                })
    findings.sort(key=lambda f: -f["gapPP"])
    return findings


def write():
    findings = scan()
    tradable = sum(1 for f in findings if f["tradable"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(findings), "tradableCount": tradable,
        "note": "Monotonie-Verletzungen in Polys eigener Strike-Leiter (modell-frei). tradable = Gap ≥ ~2× Fee.",
        "findings": findings[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Konsistenz: {len(findings)} Widersprüche ({tradable} handelbar)")


if __name__ == "__main__":
    write()
