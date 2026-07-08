#!/usr/bin/env python3
"""analysis.py — zwei Lern-Analysen (read-only) → docs/analysis.json.

1. P&L-ATTRIBUTION: Warum ist CLV grün, aber das realisierte P&L rot? Zerlegt die geschlossenen
   Trades in brutto (vor Fee) vs Fee-Last, Tail-Verlierer, Payoff-Verhältnis und — der Kern —
   Ø Fee in pp vs Ø Einstiegs-Edge in pp. (realizedPnl = brutto − feePaid, verifiziert.)

2. BTC-KLUMPEN-EXPOSURE: Ist das offene Buch in Wahrheit eine gerichtete BTC-Wette (korreliert)
   statt unabhängiges Fehlbepreisungs-Ernten? Summiert bullish/bearish nach family+side+Barriere,
   gewichtet mit einem Delta-Proxy (4·p·(1−p), am größten bei 50¢).

Rein zusammenfassend, kein Trading.
"""
from __future__ import annotations

import datetime
import json
import pathlib

DATA = pathlib.Path(__file__).parent / "data" / "paper_positions.json"
OUT = pathlib.Path(__file__).parent / "docs" / "analysis.json"


def _load():
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return []


def _round(x, n=2):
    return round(x, n) if x is not None else None


def attribution(closed: list) -> dict:
    if not closed:
        return {"nClosed": 0}
    realized = sum(p.get("realizedPnl") or 0.0 for p in closed)
    fees = sum(p.get("feePaid") or 0.0 for p in closed)
    gross = realized + fees                                  # realizedPnl = brutto − feePaid
    wins = [p for p in closed if (p.get("realizedPnl") or 0) > 0]
    losses = [p for p in closed if (p.get("realizedPnl") or 0) < 0]
    win_sum = sum(p["realizedPnl"] for p in wins)
    loss_sum = sum(p["realizedPnl"] for p in losses)
    avg_win = win_sum / len(wins) if wins else 0.0
    avg_loss = loss_sum / len(losses) if losses else 0.0
    # Ø Fee vs Ø Einstiegs-Edge, beide in pp des Einsatzes → direkt vergleichbar.
    fee_pps = [(p.get("feePaid") or 0) / (p.get("stakeUSD") or 100) * 100 for p in closed]
    edge_pps = [abs(p["entryEdgePP"]) for p in closed if p.get("entryEdgePP") is not None]
    avg_fee_pp = sum(fee_pps) / len(fee_pps) if fee_pps else 0.0
    avg_edge_pp = sum(edge_pps) / len(edge_pps) if edge_pps else 0.0
    worst = sorted(closed, key=lambda p: p.get("realizedPnl") or 0)[:5]
    best = sorted(closed, key=lambda p: p.get("realizedPnl") or 0, reverse=True)[:5]
    worst_sum = sum(p.get("realizedPnl") or 0 for p in worst)
    tail_share = (worst_sum / loss_sum) if loss_sum < 0 else None   # Anteil der 5 schlimmsten an allen Verlusten
    by_reason: dict[str, dict] = {}
    for p in closed:
        r = p.get("exitReason") or "?"
        b = by_reason.setdefault(r, {"n": 0, "pnl": 0.0})
        b["n"] += 1
        b["pnl"] += p.get("realizedPnl") or 0.0
    for b in by_reason.values():
        b["pnl"] = _round(b["pnl"])
    slim = lambda p: {"market": p.get("market"), "side": p.get("side"),
                      "pnl": _round(p.get("realizedPnl")), "reason": p.get("exitReason")}
    return {
        "nClosed": len(closed),
        "realizedTotal": _round(realized), "feesTotal": _round(fees), "grossBeforeFees": _round(gross),
        "feeDragPct": _round(fees / gross * 100) if gross > 0 else None,
        "winRate": _round(len(wins) / len(closed), 3), "nWin": len(wins), "nLoss": len(losses),
        "avgWin": _round(avg_win), "avgLoss": _round(avg_loss),
        "payoffRatio": _round(avg_win / abs(avg_loss)) if avg_loss < 0 else None,
        "avgFeePP": _round(avg_fee_pp), "avgEntryEdgePP": _round(avg_edge_pp),
        "feeEatsEdge": avg_fee_pp > avg_edge_pp,
        "worstFiveSum": _round(worst_sum), "tailLossShare": _round(tail_share, 3),
        "worst": [slim(p) for p in worst], "best": [slim(p) for p in best],
        "byReason": by_reason,
    }


def _is_up_barrier(label: str) -> bool:
    low = (label or "").lower()
    return not ("dip" in low or "below" in low or "↓" in low or "unter" in low)


def _bullish(family: str, side: str, up_barrier: bool) -> bool:
    """True = Position gewinnt, wenn BTC STEIGT."""
    yes = (side or "").upper() == "YES"
    # up-Barriere/Schwelle: YES = bullish. down-Barriere (dip): YES = bearish.
    return (up_barrier and yes) or (not up_barrier and not yes)


def btc_exposure(open_pos: list) -> dict:
    if not open_pos:
        return {"n": 0}
    long_w = short_w = 0.0
    long_stake = short_stake = 0.0
    n_long = n_short = 0
    for p in open_pos:
        stake = p.get("stakeUSD") or 100.0
        pmark = p.get("markPoly")
        pmark = pmark if pmark is not None else 0.5
        delta_proxy = 4.0 * pmark * (1.0 - pmark)          # ~Delta: max bei 50¢, ~0 an den Rändern
        w = stake * delta_proxy
        up = _is_up_barrier(p.get("market", ""))
        if _bullish(p.get("family"), p.get("side"), up):
            long_w += w; long_stake += stake; n_long += 1
        else:
            short_w += w; short_stake += stake; n_short += 1
    net_w = long_w - short_w
    tot_w = long_w + short_w
    net_pct = (net_w / tot_w * 100) if tot_w > 0 else 0.0
    direction = "LONG (steigt BTC → Buch gewinnt)" if net_w > 0 else ("SHORT (fällt BTC → Buch gewinnt)" if net_w < 0 else "neutral")
    return {
        "n": len(open_pos), "nLong": n_long, "nShort": n_short,
        "longStakeUSD": _round(long_stake), "shortStakeUSD": _round(short_stake),
        "netWeighted": _round(net_w), "grossWeighted": _round(tot_w),
        "netPct": _round(net_pct, 1),                       # +100 = komplett long, −100 = komplett short
        "direction": direction,
        # je näher |netPct| an 100, desto einseitiger die BTC-Wette (schlecht für „Fehlbepreisung ernten")
        "concentrated": abs(net_pct) >= 50,
    }


def run():
    pos = _load()
    closed = [p for p in pos if p.get("status") == "CLOSED"]
    open_pos = [p for p in pos if p.get("status") == "OPEN"]
    payload = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "attribution": attribution(closed),
        "btcExposure": btc_exposure(open_pos),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    a, e = payload["attribution"], payload["btcExposure"]
    print(f"  Analyse: brutto {a.get('grossBeforeFees')} − Fee {a.get('feesTotal')} = {a.get('realizedTotal')} "
          f"| Ø Fee {a.get('avgFeePP')}pp vs Ø Edge {a.get('avgEntryEdgePP')}pp "
          f"| BTC net {e.get('netPct')}% ({e.get('direction')})")


if __name__ == "__main__":
    run()
