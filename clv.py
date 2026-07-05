#!/usr/bin/env python3
"""clv.py — CLV-/Kalibrierungs-Auswertung aus der Edge-Historie → site/clv.json.

Zwei Metriken, ehrlich getrennt:

  1. Movement-CLV (braucht KEINE Auflösung, funktioniert sofort mit wachsender Historie):
     pro Markt Entry-Snapshot (erster Lauf mit |edge| ≥ EDGE_MIN) vs. letzter Snapshot.
     Hat sich der Poly-Preis in Richtung unseres Fair bewegt? → haben wir die Schluss-Linie
     geschlagen. Das ist der belastbare Nordstern (wie CLV gegen Pinnacle im Fußball).

  2. Kalibrierung/Hit-Rate (braucht Auflösung): Brier-Score fairProb vs. Outcome, Trefferquote
     der Edge-Picks. Gerüst steht; wird gefüllt, sobald resolutions vorliegen (TODO: Auflösungen
     über Gamma nachziehen, wenn Märkte closed sind).

READ-ONLY. Misst nur — löst keine Order aus.
"""
from __future__ import annotations

import json
import pathlib

import resolutions
import tracking

OUT = pathlib.Path(__file__).parent / "docs" / "clv.json"
EDGE_MIN = 2.0  # pp — ab hier gilt ein Markt als "Pick" fürs CLV-Tracking


def _sig_edge(s):
    """Signal-Edge fürs CLV/Pick = BRUTTO (reiner Modell-Edge fair−poly), nicht der fee-verzerrte
    Netto-Edge. CLV testet die Fair-vs-Poly-These; die (unkalibrierte) Fee gehört da nicht rein.
    Fallback auf edgePP für alte Snapshots ohne edgeGrossPP."""
    e = s.get("edgeGrossPP")
    return e if e is not None else s.get("edgePP")


def _by_market(hist):
    g = {}
    for r in hist:
        key = r.get("conditionId") or r.get("slug")
        if key:
            g.setdefault(key, []).append(r)
    for k in g:
        g[k].sort(key=lambda r: r.get("ts") or "")
    return g


def _movement_clv(groups):
    picks = []
    for cid, snaps in groups.items():
        entry = next((s for s in snaps
                      if s.get("fairProb") is not None and _sig_edge(s) is not None
                      and abs(_sig_edge(s)) >= EDGE_MIN), None)
        if not entry:
            continue
        last = snaps[-1]
        if last.get("polyPrice") is None or entry.get("polyPrice") is None:
            continue
        sign = 1.0 if _sig_edge(entry) > 0 else -1.0   # edge>0 = Yes unterbepreist → Yes kaufen
        clv_pp = round((last["polyPrice"] - entry["polyPrice"]) * 100.0 * sign, 2)
        picks.append({
            "conditionId": cid,
            "market": entry.get("market") or entry.get("slug"),
            "entryEdgePP": _sig_edge(entry),
            "entryPoly": entry["polyPrice"],
            "lastPoly": last["polyPrice"],
            "clvPP": clv_pp,
            "entryAgeH": entry.get("ageH"),
            "snapshots": len(snaps),
        })
    return picks


def _first_pick(snaps):
    return next((s for s in snaps
                 if s.get("fairProb") is not None and _sig_edge(s) is not None
                 and abs(_sig_edge(s)) >= EDGE_MIN), None)


def _calibration(groups, res):
    """Auflösungs-basiert: Brier (uns vs Poly), Hit-Rate + realisierter Brutto-PnL der Picks."""
    brier_ours, brier_poly, pnls, wins = [], [], [], 0
    resolved_picks = 0
    for cid, snaps in groups.items():
        r = res.get(cid)
        if not r:
            continue
        outcome = r["outcome"]
        fair_snap = next((s for s in snaps if s.get("fairProb") is not None), None)
        if fair_snap:
            brier_ours.append((fair_snap["fairProb"] - outcome) ** 2)
            brier_poly.append((fair_snap["polyPrice"] - outcome) ** 2)
        pick = _first_pick(snaps)
        if pick:
            resolved_picks += 1
            sign = 1.0 if _sig_edge(pick) > 0 else -1.0       # edge>0 = Yes kaufen, sonst No
            won = (outcome == 1) if sign > 0 else (outcome == 0)
            wins += 1 if won else 0
            pnls.append(sign * (outcome - pick["polyPrice"]))  # Brutto-PnL je $1 Einsatz
    bo = round(sum(brier_ours) / len(brier_ours), 4) if brier_ours else None
    bp = round(sum(brier_poly) / len(brier_poly), 4) if brier_poly else None
    return {
        "resolvedMarkets": len(brier_ours),
        "resolvedPicks": resolved_picks,
        "hitRate": round(wins / resolved_picks, 3) if resolved_picks else None,
        "avgRealizedPnlPP": round(sum(pnls) / len(pnls) * 100, 2) if pnls else None,
        "brierOurs": bo,
        "brierPoly": bp,
        "betterThanPoly": round(bp - bo, 4) if (bo is not None and bp is not None) else None,
        "note": "PnL brutto (vor Fee). betterThanPoly>0 = unser Fair besser kalibriert als der Poly-Preis.",
    }


_AGE_BUCKETS = [(6, "0-6h"), (24, "6-24h"), (72, "1-3d")]


def _age_bucket(h):
    if h is None:
        return "unbek."
    for lim, name in _AGE_BUCKETS:
        if h < lim:
            return name
    return ">3d"


def _cohorts(picks):
    """Movement-CLV nach Markt-Alter beim Einstieg — testet die Neu-Markt-Lag-These:
    ist der CLV bei jungen Märkten (0-6h) höher als bei etablierten?"""
    buckets = {}
    for p in picks:
        buckets.setdefault(_age_bucket(p.get("entryAgeH")), []).append(p["clvPP"])
    out = {}
    for b, vals in buckets.items():
        out[b] = {"picks": len(vals), "avgClvPP": round(sum(vals) / len(vals), 2),
                  "positiveShare": round(sum(1 for v in vals if v > 0) / len(vals), 2)}
    return out


def _trends(groups, n=24):
    """Letzte n Netto-Edge-Punkte je Markt (für Mini-Sparklines im Dashboard)."""
    out = {}
    for cid, snaps in groups.items():
        series = [s["edgePP"] for s in snaps if s.get("edgePP") is not None][-n:]
        if series:
            out[cid] = series
    return out


def compute(hist=None):
    hist = hist if hist is not None else tracking.load_history()
    res = resolutions.load_resolutions()
    groups = _by_market(hist)
    picks = _movement_clv(groups)
    n = len(picks)
    summary = {
        "trackedMarkets": len(groups),
        "picks": n,
        "avgClvPP": round(sum(p["clvPP"] for p in picks) / n, 2) if n else None,
        "positiveClvShare": round(sum(1 for p in picks if p["clvPP"] > 0) / n, 2) if n else None,
        "edgeMinPP": EDGE_MIN,
        "note": "Movement-CLV: bewegt sich Poly zum Fair? Positiv = Schluss-Linie geschlagen.",
    }
    return {
        "summary": summary,
        "calibration": _calibration(groups, res),
        "cohorts": _cohorts(picks),
        "trends": _trends(groups),
        "picks": sorted(picks, key=lambda p: p["clvPP"], reverse=True)[:50],
    }


def write():
    data = compute()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  CLV → {data['summary']}")
    return data


if __name__ == "__main__":
    write()
