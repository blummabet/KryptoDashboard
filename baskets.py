#!/usr/bin/env python3
"""baskets.py — Modellfreier Multi-Outcome-Basket-Arb über ALLE Poly-Kategorien → docs/baskets.json.

Idee (Lucas): Märkte mit vielen exklusiven Antworten ("Wer wird Weltmeister?", "Wer gewinnt die Wahl?").
Bei einem negRisk-Event zahlt am Ende GENAU ein Kandidat $1. Also muss Σ aller Yes-Preise = 1 sein.
Weicht die Summe ab, ist das eine RISIKOFREIE Kante — ganz OHNE Referenzmodell (kein Deribit nötig):

  · SELL-Basket  (Σ Yes-Bid > 1):  alle Yes verkaufen (= alle No am Ask kaufen). Auszahlung genau $1,
    Einnahme > $1 → sicherer Gewinn. Robust — gilt AUCH wenn es einen unnotierten "Other"-Ausgang gibt.
  · BUY-Basket   (Σ Yes-Ask < 1):  alle Yes kaufen. Sicherer Gewinn NUR wenn die Kandidaten
    ERSCHÖPFEND sind (kein "Other"/"Field"-Ausgang) — sonst zahlt bei "Other" jedes Bein $0. → Caveat.

EHRLICH: „Einsteigen und bei Profit raus" ist für sich KEINE Kante (Phantom-Edge). Die einzige
belastbare, referenzfreie Kante hier ist genau diese Σ≠1-Arb. Auf liquiden Märkten (WM, Wahlen) ist
sie durch den Overround meist wegarbitriert; sie taucht in dünnen/frischen Multi-Outcome-Märkten auf.
READ-ONLY. Kein echtes Geld.
"""
from __future__ import annotations

import datetime
import json
import pathlib

import poly_core

OUT = pathlib.Path(__file__).parent / "docs" / "baskets.json"
MIN_LEGS = 3            # unter 3 Kandidaten kein sinnvoller "Basket"
NET_FLOOR_PP = 0.5     # ab hier überhaupt anzeigen (nach Fee)
TRADABLE_PP = 1.5      # ab hier als handelbar markieren (Puffer über Slippage)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fee_rate(m: dict) -> float:
    fs = m.get("feeSchedule") or {}
    r = _f(fs.get("rate"))
    return r if r is not None else 0.07   # konservativer Default (Krypto-Satz)


def _leg(m: dict) -> dict:
    return {
        "name": m.get("groupItemTitle") or (m.get("question") or "")[:40],
        "bid": _f(m.get("bestBid")), "ask": _f(m.get("bestAsk")),
        "rate": _fee_rate(m), "clobTokenIds": _parse_ids(m.get("clobTokenIds")),
        "conditionId": m.get("conditionId"),
    }


def _parse_ids(v):
    try:
        j = json.loads(v) if isinstance(v, str) else v
        return j if isinstance(j, list) and len(j) >= 2 else None
    except Exception:
        return None


def _event_of(m: dict) -> dict:
    evs = m.get("events") or []
    return evs[0] if evs else {}


def scan(markets: list) -> list:
    """Gruppiert flache negRisk-Kandidatenmärkte nach negRiskMarketID (= Korb) und rechnet die Gaps."""
    groups: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for m in markets:
        if m.get("closed") or not m.get("negRisk"):
            continue
        key = m.get("negRiskMarketID") or _event_of(m).get("id")
        if not key:
            continue
        groups.setdefault(key, []).append(m)
        if key not in meta:
            ev = _event_of(m)
            meta[key] = {"event": (ev.get("title") or "").strip() or key,
                         "slug": ev.get("slug"), "endDate": ev.get("endDate")}

    findings = []
    for key, ms in groups.items():
        legs = [_leg(m) for m in ms]
        n = len(legs)
        if n < MIN_LEGS:
            continue
        have_bid = [l for l in legs if l["bid"] is not None]
        have_ask = [l for l in legs if l["ask"] is not None]
        complete_bid = len(have_bid) == n
        complete_ask = len(have_ask) == n

        sum_bid = sum(l["bid"] for l in have_bid) if have_bid else None
        sum_ask = sum(l["ask"] for l in have_ask) if have_ask else None

        rec = None
        # SELL-Basket: Σ Yes-Bid > 1 → robust risikofrei (auch mit "Other"-Ausgang).
        if complete_bid and sum_bid is not None and sum_bid > 1.0:
            gross = (sum_bid - 1.0) * 100.0
            fee = sum(l["rate"] * min(1 - l["bid"], l["bid"]) for l in have_bid) * 100.0
            net = gross - fee
            if net >= NET_FLOOR_PP:
                rec = {"side": "sell", "sumProb": round(sum_bid, 4), "grossPP": round(gross, 2),
                       "feePP": round(fee, 2), "netPP": round(net, 2), "exhaustiveNeeded": False,
                       "note": "alle Yes verkaufen (alle No kaufen) — robust risikofrei"}
        # BUY-Basket: Σ Yes-Ask < 1 → nur risikofrei wenn erschöpfend (kein "Other").
        elif complete_ask and sum_ask is not None and sum_ask < 1.0:
            gross = (1.0 - sum_ask) * 100.0
            fee = sum(l["rate"] * min(l["ask"], 1 - l["ask"]) for l in have_ask) * 100.0
            net = gross - fee
            if net >= NET_FLOOR_PP:
                rec = {"side": "buy", "sumProb": round(sum_ask, 4), "grossPP": round(gross, 2),
                       "feePP": round(fee, 2), "netPP": round(net, 2), "exhaustiveNeeded": True,
                       "note": "alle Yes kaufen — nur risikofrei wenn Kandidaten erschöpfend (kein 'Other')"}

        if rec:
            rec.update({
                "negRiskMarketID": key, "event": meta[key]["event"], "slug": meta[key]["slug"],
                "endDate": meta[key]["endDate"], "n": n,
                "completeBid": complete_bid, "completeAsk": complete_ask,
                # handelbar nur wenn Netto-Gap groß genug UND (sell-Seite ODER erschöpfend markiert)
                "tradable": rec["netPP"] >= TRADABLE_PP and (rec["side"] == "sell"),
                "top": sorted([{"name": l["name"], "bid": l["bid"], "ask": l["ask"]} for l in legs],
                              key=lambda x: -(x["ask"] or 0))[:6],
            })
            findings.append(rec)

    findings.sort(key=lambda f: -f["netPP"])
    return findings


def write():
    try:
        markets = poly_core.gamma_markets_negrisk()
    except Exception as e:
        print(f"  ⚠️ baskets: Fetch fehlgeschlagen ({e}) — schreibe leeren Stand")
        markets = []
    findings = scan(markets)
    tradable = [f for f in findings if f["tradable"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scanned": len(markets), "count": len(findings), "tradableCount": len(tradable),
        "note": ("Modellfreier Multi-Outcome-Basket-Arb (Σ Yes ≠ 1) über alle Kategorien. "
                 "SELL-Seite robust risikofrei; BUY-Seite nur bei erschöpfenden Kandidaten. "
                 "read-only · 'einsteigen & bei Profit raus' ist KEINE Kante — nur die Σ≠1-Arb ist eine."),
        "findings": findings[:60],
    }, indent=2, ensure_ascii=False))
    print(f"  Baskets: {len(markets)} Kandidaten gescannt, {len(findings)} Σ≠1-Funde "
          f"({len(tradable)} robust handelbar)")


if __name__ == "__main__":
    write()
