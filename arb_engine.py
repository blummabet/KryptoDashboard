#!/usr/bin/env python3
"""arb_engine.py — Paper-Buch für die Cross-Market-Konsistenz-Arbitrage (dry-run) → docs/arb.json.

Findet Widersprüche (consistency.scan) und handelt sie auf PAPIER als risikoarme Arb:
kauft Yes auf dem BREITEREN Event (Superset = billigere Seite) + No auf dem ENGEREN (Subset = teurere).
Auszahlung ≥ 1 garantiert, Einstand < 1 → gesperrter Mindestgewinn = gap (minus 2 Taker-Fees).
Hält beide Beine bis zur Auflösung, settlet dann zum echten Outcome. KEIN echtes Geld.
"""
from __future__ import annotations

import datetime
import json
import pathlib

import consistency
import fair_value
import resolutions

MARKETS = pathlib.Path(__file__).parent / "docs" / "markets.json"
POSITIONS = pathlib.Path(__file__).parent / "data" / "arb_positions.json"
OUT = pathlib.Path(__file__).parent / "docs" / "arb.json"
STAKE_USD = 100.0


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_markets():
    try:
        return json.loads(MARKETS.read_text(encoding="utf-8")).get("markets", [])
    except Exception:
        return []


def _load_positions():
    if POSITIONS.exists():
        try:
            return json.loads(POSITIONS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _key(f):
    return "|".join(sorted([str(f.get("lowCid")), str(f.get("highCid"))]))


def run():
    now = _now()
    markets = _load_markets()
    findings = consistency.scan(markets)
    positions = _load_positions()
    res = resolutions.load_resolutions()
    open_keys = {p["key"] for p in positions if p["status"] == "OPEN"}
    activity = []

    # 1) Offene Arbs settlen, sobald BEIDE Beine aufgelöst sind.
    for p in positions:
        if p["status"] != "OPEN":
            continue
        rc, rs = res.get(p["supersetCid"]), res.get(p["subsetCid"])
        if rc is not None and rs is not None:
            payoff = float(rc["outcome"]) + (1.0 - float(rs["outcome"]))   # Yes(superset)+No(subset) ≥ 1
            pnl = p["shares"] * (payoff - p["cost"]) - p["feePaid"]
            p["status"] = "CLOSED"
            p["exitTs"] = now
            p["payoff"] = payoff
            p["realizedPnl"] = round(pnl, 2)
            p["roiPct"] = round(pnl / STAKE_USD * 100, 1)
            activity.append({"ts": now, "type": "settle", "market": p["label"], "pnl": p["realizedPnl"]})

    # 2) Neue handelbare Widersprüche eröffnen (Gap ≥ ~2× Fee).
    for f in findings:
        if not f.get("tradable") or not f.get("lowCid") or not f.get("highCid"):
            continue
        k = _key(f)
        if k in open_keys:
            continue
        # billigere Seite = Superset (Yes kaufen), teurere = Subset (No kaufen)
        if f["lowP"] <= f["highP"]:
            sup_cid, sup_p, sub_cid, sub_p = f["lowCid"], f["lowP"], f["highCid"], f["highP"]
        else:
            sup_cid, sup_p, sub_cid, sub_p = f["highCid"], f["highP"], f["lowCid"], f["lowP"]
        cost = sup_p + (1.0 - sub_p)
        if not (0 < cost < 1):
            continue
        shares = round(STAKE_USD / cost, 2)
        fee = STAKE_USD * (fair_value.estimated_fee_pp(sup_p) + fair_value.estimated_fee_pp(1 - sub_p)) / 100.0
        positions.append({
            "key": k, "status": "OPEN", "entryTs": now, "label": f["note"],
            "supersetCid": sup_cid, "subsetCid": sub_cid, "supP": sup_p, "subP": sub_p,
            "cost": round(cost, 4), "gapPP": f["gapPP"], "shares": shares, "feePaid": round(fee, 2),
            "lockedMin": round(shares * (f["gapPP"] / 100.0) - fee, 2),
        })
        open_keys.add(k)
        activity.append({"ts": now, "type": "open", "market": f["note"], "gap": f["gapPP"]})

    POSITIONS.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS.write_text(json.dumps(positions, indent=2, ensure_ascii=False))
    _write(findings, positions, now, activity)
    print(f"  Arb-Buch: {sum(1 for p in positions if p['status']=='OPEN')} offen, "
          f"{sum(1 for p in positions if p['status']=='CLOSED')} settled")


def _write(findings, positions, now, activity):
    open_pos = [p for p in positions if p["status"] == "OPEN"]
    closed = [p for p in positions if p["status"] == "CLOSED"]
    realized = sum(p.get("realizedPnl", 0.0) for p in closed)
    locked = sum(p.get("lockedMin", 0.0) for p in open_pos)   # garantierter Mindestgewinn offen
    wins = sum(1 for p in closed if p.get("realizedPnl", 0.0) > 0)
    summary = {
        "mode": "PAPER / DRY-RUN",
        "totalPnl": round(realized + locked, 2), "realizedPnl": round(realized, 2),
        "lockedOpen": round(locked, 2), "openCount": len(open_pos), "closedCount": len(closed),
        "winRate": round(wins / len(closed), 3) if closed else None, "stakeUSD": STAKE_USD,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": now, "count": len(findings),
        "tradableCount": sum(1 for f in findings if f["tradable"]),
        "note": "Monotonie-Verletzungen in Polys eigener Strike-Leiter (modell-frei) — auf Papier gehandelt.",
        "paper": {
            "summary": summary,
            "open": [{"label": p["label"], "gapPP": p["gapPP"], "cost": p["cost"],
                      "lockedMin": p["lockedMin"], "entryTs": p["entryTs"]} for p in open_pos][:60],
            "closed": sorted(closed, key=lambda p: p.get("exitTs", ""), reverse=True)[:60],
            "activity": list(reversed(activity))[:40],
        },
        "findings": findings[:60],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
