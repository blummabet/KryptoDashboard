#!/usr/bin/env python3
"""scoreboard.py — Tages-Verlauf aller Test-Stränge → docs/scoreboard.json.

Damit Lucas ÜBER TAGE sieht, was jede Strategie abwirft (nicht nur die Momentaufnahme).
Liest die Kennzahlen aus den anderen docs/*.json, schreibt EINE Zeile pro UTC-Tag fort
(gleicher Tag = überschreiben, sonst anhängen). Read-only, rein zusammenfassend.
"""
from __future__ import annotations

import datetime
import json
import pathlib

DOCS = pathlib.Path(__file__).parent / "docs"
OUT = DOCS / "scoreboard.json"
KEEP_DAYS = 180


def _load(name: str) -> dict:
    try:
        return json.loads((DOCS / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def snapshot() -> dict:
    paper = _load("paper.json").get("summary", {})
    arb = (_load("arb.json").get("paper") or {}).get("summary", {})
    baskets = _load("baskets.json")
    mk = _load("maker.json")
    msim = mk.get("sim", {})
    mo = mk.get("markout", {})
    clv = _load("clv.json").get("summary", {})
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return {
        "date": day,
        # Konvergenz (Taker, Papier)
        "convergePnl": paper.get("totalPnl"),
        "convergeRealized": paper.get("realizedPnl"),
        "convergeWinRate": paper.get("winRate"),
        "newMarketPnl": paper.get("newMarketPnl"),
        # Konsistenz-Arb
        "arbLocked": arb.get("lockedOpen"),
        "arbPnl": arb.get("totalPnl"),
        "arbOpen": arb.get("openCount"),
        # Maker
        "makerCumReward": msim.get("cumRewardEst"),
        "makerRewardDay": msim.get("estRewardDayTotal"),
        "makerMarkoutPP": mo.get("avgMarkoutPP"),
        # Multi-Outcome Basket
        "basketFinds": baskets.get("count"),
        "basketTradable": baskets.get("tradableCount"),
        # Nordstern CLV
        "clvPP": clv.get("avgClvPP"),
        "clvPositiveShare": clv.get("positiveClvShare"),
    }


def run():
    row = snapshot()
    hist = []
    if OUT.exists():
        try:
            hist = json.loads(OUT.read_text(encoding="utf-8")).get("days", [])
        except Exception:
            hist = []
    if hist and hist[-1].get("date") == row["date"]:
        hist[-1] = row                      # gleicher Tag → aktualisieren
    else:
        hist.append(row)
    hist = hist[-KEEP_DAYS:]
    start = hist[0]["date"] if hist else row["date"]
    OUT.write_text(json.dumps({
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "startDate": start, "dayNo": len(hist), "latest": row, "days": hist,
    }, indent=2, ensure_ascii=False))
    print(f"  Scoreboard: Tag {len(hist)} (seit {start}) → {OUT}")


if __name__ == "__main__":
    run()
