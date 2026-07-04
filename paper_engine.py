#!/usr/bin/env python3
"""paper_engine.py — Dry-Run Paper-Trading (Phase 3). KEIN echtes Geld, alle Schalter AUS.

Liest die aktuelle Edge-Tabelle (docs/markets.json) + Auflösungen, verwaltet Papier-Positionen
(data/paper_positions.json) und schreibt die Dashboard-Sicht (docs/paper.json).

Strategie = KONVERGENZ, nicht Vorhersage:
  · ÖFFNEN: Netto-Edge ≥ EDGE_FLOOR, Liquidität ≥ LIQ_FLOOR, noch keine Position offen, Cap frei.
    Seite = YES bei Edge>0 (Yes unterbepreist), NO bei Edge<0. Einstieg = aktueller Poly-Preis.
  · JE LAUF prüfen (remaining = Edge in unsere Richtung: edge wenn YES, −edge wenn NO):
      - remaining ≤ THESIS_BREAK → schließen "thesis_break" (unsere Fair stützt die Position nicht mehr)
      - remaining ≤ CONVERGE_AT  → schließen "converged" (Poly zur Fair aufgeschlossen → Edge kassiert)
      - Markt verschwunden + aufgelöst → settle zum Outcome (resolved_win/loss)
  · KEIN fixer %-Stop (falsch für Konvergenz). Geschätzte Taker-Fee bei Ein-/aktivem Ausstieg abgezogen.

PnL je Position (Papier): YES → shares·(mark−entry), NO → shares·(entry−mark); mark = aktueller
Poly-Preis (unrealisiert) oder Outcome 0/1 (realisiert). shares = STAKE/Einstandspreis.
"""
from __future__ import annotations

import datetime
import json
import pathlib

import fair_value
import resolutions

MARKETS = pathlib.Path(__file__).parent / "docs" / "markets.json"
POSITIONS = pathlib.Path(__file__).parent / "data" / "paper_positions.json"
OUT = pathlib.Path(__file__).parent / "docs" / "paper.json"

# ── Konfiguration — klein & gedeckelt (das sind die "Schalter", alle konservativ) ──────────────
STAKE_USD       = 100.0   # Papier-Einsatz je Position
EDGE_FLOOR_PP   = 2.5     # ab hier öffnen (Netto-Edge nach geschätzter Fee)
LIQ_FLOOR_USD   = 5000.0  # dünne Märkte überspringen
MAX_OPEN        = 40      # gedeckelte Anzahl gleichzeitig offener Positionen
CONVERGE_AT_PP  = 0.5     # Gewinn realisieren, wenn Edge auf ~0 geschlossen ist
THESIS_BREAK_PP = -2.5    # Reißleine, wenn der Edge deutlich gegen uns dreht (Fair war falsch)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_positions():
    if POSITIONS.exists():
        try:
            return json.loads(POSITIONS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _load_markets():
    try:
        return json.loads(MARKETS.read_text(encoding="utf-8")).get("markets", [])
    except Exception:
        return []


def _mark_pnl(pos, mark):
    """PnL (vor Fee) bei Bewertung 'mark' (Poly-Preis oder Outcome)."""
    if pos["side"] == "YES":
        return pos["shares"] * (mark - pos["entryPoly"])
    return pos["shares"] * (pos["entryPoly"] - mark)


def _fee_usd(price):
    return STAKE_USD * (fair_value.estimated_fee_pp(price) / 100.0)


def _age_hours(ts, now):
    try:
        a = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        b = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))
        return round((b - a).total_seconds() / 3600, 1)
    except Exception:
        return None


def _open(m, now):
    edge, p = m.get("edgePP"), m.get("polyPrice")
    side = "YES" if edge > 0 else "NO"
    cost_price = p if side == "YES" else 1.0 - p
    if not (0.02 <= cost_price <= 0.98):      # zu extrem → kein sinnvoller Einstieg
        return None
    return {
        "conditionId": m["conditionId"], "slug": m.get("slug"), "market": m.get("market"),
        "family": m.get("family"), "side": side, "status": "OPEN",
        "entryTs": now, "entryPoly": round(p, 4), "entryFair": m.get("fairProb"),
        "entryEdgePP": edge, "shares": round(STAKE_USD / cost_price, 2), "stakeUSD": STAKE_USD,
        "feePaid": round(_fee_usd(cost_price), 2),
    }


def _close(pos, mark, reason, now, exit_fee=0.0):
    pos["status"] = "CLOSED"
    pos["exitTs"] = now
    pos["exitMark"] = round(mark, 4)
    pos["exitReason"] = reason
    pos["feePaid"] = round(pos.get("feePaid", 0.0) + exit_fee, 2)
    pnl = _mark_pnl(pos, mark) - pos["feePaid"]
    pos["realizedPnl"] = round(pnl, 2)
    pos["roiPct"] = round(pnl / pos["stakeUSD"] * 100, 1)


def run():
    now = _now()
    positions = _load_positions()
    mkts = {m["conditionId"]: m for m in _load_markets() if m.get("conditionId")}
    res = resolutions.load_resolutions()
    activity = []

    # 1) Offene Positionen aktualisieren / schließen
    for pos in positions:
        if pos["status"] != "OPEN":
            continue
        cid = pos["conditionId"]
        m = mkts.get(cid)
        if m and m.get("edgePP") is not None and m.get("polyPrice") is not None:
            edge, poly = m["edgePP"], m["polyPrice"]
            remaining = edge if pos["side"] == "YES" else -edge
            exit_price = poly if pos["side"] == "YES" else 1.0 - poly
            if remaining <= THESIS_BREAK_PP:
                _close(pos, poly, "thesis_break", now, _fee_usd(exit_price))
                activity.append({"ts": now, "type": "close", "reason": "thesis_break",
                                 "market": pos["market"], "pnl": pos["realizedPnl"]})
            elif remaining <= CONVERGE_AT_PP:
                _close(pos, poly, "converged", now, _fee_usd(exit_price))
                activity.append({"ts": now, "type": "close", "reason": "converged",
                                 "market": pos["market"], "pnl": pos["realizedPnl"]})
            else:
                pos["markPoly"] = round(poly, 4)   # weiter halten, für Unrealized markieren
                pos["curEdgePP"] = edge
        elif cid in res:                            # Markt weg + aufgelöst → settlen
            outcome = float(res[cid]["outcome"])
            won = _mark_pnl(pos, outcome) > 0
            _close(pos, outcome, "resolved_win" if won else "resolved_loss", now)
            activity.append({"ts": now, "type": "settle", "reason": "resolved",
                             "market": pos["market"], "pnl": pos["realizedPnl"]})
        # sonst: Markt temporär nicht in der Tabelle → offen lassen

    open_cids = {p["conditionId"] for p in positions if p["status"] == "OPEN"}

    # 2) Neue Positionen öffnen (stärkster Edge zuerst, Cap beachten)
    n_open = len(open_cids)
    # Neu-Markt-Lag: frische Märkte zuerst (Poly noch nicht zur Referenz konvergiert), dann nach Edge.
    cands = sorted(
        (m for m in mkts.values()
         if m.get("edgePP") is not None and m.get("fairProb") is not None
         and abs(m["edgePP"]) >= EDGE_FLOOR_PP and (m.get("liquidityUSD") or 0) >= LIQ_FLOOR_USD),
        key=lambda m: (not m.get("isNew", False), -abs(m["edgePP"])))
    for m in cands:
        if n_open >= MAX_OPEN:
            break
        if m["conditionId"] in open_cids:
            continue
        pos = _open(m, now)
        if pos:
            positions.append(pos)
            open_cids.add(m["conditionId"])
            n_open += 1
            activity.append({"ts": now, "type": "open", "side": pos["side"],
                             "market": pos["market"], "entry": pos["entryPoly"],
                             "edge": pos["entryEdgePP"]})

    POSITIONS.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS.write_text(json.dumps(positions, indent=2, ensure_ascii=False))
    _write_view(positions, now, activity)
    print(f"  Paper: {n_open} offen, {sum(1 for p in positions if p['status']=='CLOSED')} geschlossen")


def _write_view(positions, now, activity):
    open_pos = [p for p in positions if p["status"] == "OPEN"]
    closed = [p for p in positions if p["status"] == "CLOSED"]

    unreal = 0.0
    open_rows = []
    for p in open_pos:
        mark = p.get("markPoly", p["entryPoly"])
        u = _mark_pnl(p, mark) - p["feePaid"]
        unreal += u
        open_rows.append({
            "market": p["market"], "family": p.get("family"), "side": p["side"],
            "entryPoly": p["entryPoly"], "markPoly": mark, "curEdgePP": p.get("curEdgePP"),
            "entryEdgePP": p["entryEdgePP"], "unrealPnl": round(u, 2),
            "ageH": _age_hours(p["entryTs"], now),
        })

    realized = sum(p.get("realizedPnl", 0.0) for p in closed)
    wins = sum(1 for p in closed if p.get("realizedPnl", 0.0) > 0)
    summary = {
        "mode": "PAPER / DRY-RUN — kein echtes Geld",
        "totalPnl": round(realized + unreal, 2),
        "realizedPnl": round(realized, 2),
        "unrealizedPnl": round(unreal, 2),
        "openCount": len(open_pos),
        "closedCount": len(closed),
        "winRate": round(wins / len(closed), 3) if closed else None,
        "roiPct": round(realized / (STAKE_USD * len(closed)) * 100, 1) if closed else None,
        "stakedOpenUSD": round(STAKE_USD * len(open_pos)),
        "stakeUSD": STAKE_USD, "edgeFloorPP": EDGE_FLOOR_PP,
    }
    view = {
        "generatedAt": now, "summary": summary,
        "open": sorted(open_rows, key=lambda r: -(r["unrealPnl"] or 0))[:100],
        "closed": sorted(closed, key=lambda p: p.get("exitTs", ""), reverse=True)[:60],
        "activity": list(reversed(activity))[:40],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(view, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
