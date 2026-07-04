#!/usr/bin/env python3
"""build_markets.py — Phase-1-Pipeline: Poly-Tages-Schwellenmärkte → site/markets.json.

READ-ONLY. KEIN Trading. Fair Value = europäisches Digital auf Deribit-Forward + Smile-IV
(pro Strike/Verfall). Familie C: btc-multi-strikes-weekly ("BTC über $X on <Datum>", europäisch,
Auflösung Binance-Close). Barriere-Familien (hit/ATH) bewusst (noch) NICHT drin.

Lehre: nur Code committen — die Daten (markets.json) heilen sich über den Actions-Cron.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re

import data_sources
import fair_value
import guards
import poly_core
import tracking
from signals.context_signals import FearGreedSignal
from signals.registry import SignalRegistry

OUT = pathlib.Path(__file__).parent / "docs" / "markets.json"

# Familien (BTC, read-only). 'above' = europ. Digital (Preis am Stichtag), 'touch' = One-Touch-Barriere.
SERIES = [
    {"slug": "btc-multi-strikes-weekly", "family": "above"},   # Tages-Schwelle "über $X am Stichtag"
    {"slug": "bitcoin-hit-price-monthly", "family": "touch"},  # One-Touch "hit $X" / "dip $X" bis Datum
]
_YEAR_SECS = 365.0 * 24 * 3600
_MONTH_WORDS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def parse_strike(m: dict):
    """Strike + Richtung aus groupItemTitle ('70,000', '↑ 65,000', '↓ 45,000').
    Datum-Titel (z.B. ATH 'December 31, 2026') → kein Preis-Strike → None (übersprungen)."""
    t = (m.get("groupItemTitle") or m.get("question") or "")
    low = t.lower()
    if any(w in low for w in _MONTH_WORDS):
        return None, "above"
    digits = re.sub(r"[^\d]", "", t)
    strike = int(digits) if digits else None
    down = ("↓" in t) or ("dip" in low) or ("below" in low)
    return strike, ("below" if down else "above")


def yes_price(m: dict):
    try:
        return float(json.loads(m.get("outcomePrices") or "[]")[0])
    except Exception:
        return None


NEW_HOURS = 48   # jünger = "neu" → Neu-Markt-Lag (Poly noch nicht konvergiert)


def _end_dt(end_iso: str | None):
    if not end_iso:
        return None
    try:
        return datetime.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_h(start_iso: str | None):
    dt = _end_dt(start_iso)
    if not dt:
        return None
    return round((datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600, 1)


def t_years(end_dt):
    if not end_dt:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    return max((end_dt - now).total_seconds(), 0.0) / _YEAR_SECS


def build():
    # Referenz-Spot nur zur Auflösungs-Sanity (Binance = Auflösungsquelle; Fallback Deribit-Index).
    spot = data_sources.binance_spot("BTCUSDT")
    spot_src = "binance"
    if spot is None:
        spot = data_sources.deribit_index("BTC")
        spot_src = "deribit ⚠️ (≠ Auflösung Binance = Basis-Risiko)"

    rows = []
    atm_iv = None  # repräsentative IV für die Referenz-Zeile (Strike am nächsten zum Spot)
    atm_dist = None

    for cfg in SERIES:
        slug, family = cfg["slug"], cfg["family"]
        for ev in poly_core.gamma_events(slug):
            # Hinweis: 'hide-from-new' NICHT als Ausschluss nutzen — Polymarket taggt damit ALLE
            # wiederkehrenden Märkte (auch unsere Schwellen). Die Serien-Filterung reicht.
            for m in ev.get("markets", []):
                if poly_core.is_derived_market(m.get("slug", "")):
                    continue
                strike, direction = parse_strike(m)
                poly = yes_price(m)
                if strike is None or poly is None:
                    continue
                end_dt = _end_dt(m.get("endDate") or ev.get("endDate"))
                T = t_years(end_dt)

                fair = iv = None
                if T and end_dt:
                    fi = data_sources.deribit_fair_inputs(strike, end_dt.date(), "BTC")
                    if fi:
                        iv = fi["iv"]
                        if family == "touch":
                            # One-Touch-Barriere auf dem realen Kurspfad → Spot als S0 (nicht Forward).
                            fair = fair_value.one_touch(spot or fi["forward"], strike, iv, T)
                        else:  # 'above' — europ. Digital am Stichtag (Forward-konsistent)
                            fair = (fair_value.digital_above(fi["forward"], strike, iv, T)
                                    if direction == "above"
                                    else fair_value.digital_below(fi["forward"], strike, iv, T))
                        if spot and family == "above":  # repräsentative ATM-IV nur aus Digitals
                            d = abs(strike - spot)
                            if atm_dist is None or d < atm_dist:
                                atm_dist, atm_iv = d, iv

                if family == "touch":
                    verb = "dip" if direction == "below" else "erreicht"
                    label = f"{verb} ${strike:,} bis {m.get('endDateIso') or ''}"
                else:
                    label = f"über ${strike:,} · {m.get('endDateIso') or ''}"

                rows.append({
                    "asset": "BTC",
                    "family": family,
                    "conditionId": m.get("conditionId"),
                    "slug": m.get("slug"),
                    "endDate": m.get("endDate") or ev.get("endDate"),
                    "market": label,
                    "strike": strike,
                    "direction": direction,
                    "spot": round(spot) if spot else None,
                    "ivPct": round(iv * 100, 1) if iv is not None else None,
                    "polyPrice": round(poly, 4),
                    "fairProb": round(fair, 4) if fair is not None else None,
                    "edgePP": fair_value.net_edge_pp(fair, poly),       # netto (nach geschätzter Fee)
                    "edgeGrossPP": fair_value.gross_edge_pp(fair, poly),
                    "liquidityUSD": round(m.get("liquidityNum") or 0),
                    # Maker-/Freshness-Felder:
                    "bestBid": m.get("bestBid"),
                    "bestAsk": m.get("bestAsk"),
                    "rewardsMinSize": m.get("rewardsMinSize"),
                    "rewardsMaxSpread": m.get("rewardsMaxSpread"),
                    "ageH": _age_h(m.get("startDate")),
                    "isNew": (_age_h(m.get("startDate")) or 1e9) < NEW_HOURS,
                })

    rows.sort(key=lambda r: (r["edgePP"] is None, -(r["edgePP"] or 0)))

    # Guard-Batterie: stille Fehler aufdecken, bevor wir schreiben (Daten heilen sich, aber laut loggen).
    for msg in guards.check_reference(spot, atm_iv):
        print(f"  ⚠️ GUARD reference: {msg}")
    issues = guards.audit_rows(rows)
    for key, warns in issues.items():
        print(f"  ⚠️ GUARD {key}: {'; '.join(warns)}")

    # Kontext-Layer (Display/Regime, getrennt vom Trade-Edge). Erst F&G, weitere folgen.
    context = {"fearGreed": data_sources.fear_greed()}
    reg = SignalRegistry()
    reg.register(FearGreedSignal())
    context_signals = [
        {"name": r.name, "family": r.family, "adjPP": r.adj_pp, "evidence": r.evidence, "silent": r.silent}
        for r in reg.evaluate_all({"context": context})
    ]

    payload = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "reference": {"spot": round(spot) if spot else None, "spotSource": spot_src,
                      "iv": round(atm_iv, 4) if atm_iv is not None else None},
        "note": ("read-only · Schwelle = europ. Digital, Touch = One-Touch-Barriere (Deribit-Smile-IV) · "
                 "edge = NETTO (nach geschätzter Taker-Fee) · edgeGrossPP = brutto"),
        "context": context,
        "contextSignals": context_signals,
        "markets": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"  → {len(rows)} Märkte nach {OUT} (spot={spot} via {spot_src}, atm_iv={atm_iv})")

    # Nordstern: jeden Lauf in die Edge-Historie schreiben (für CLV).
    ts = tracking.append_snapshots(rows)
    print(f"  Snapshot @ {ts} → {tracking.HIST}")


if __name__ == "__main__":
    build()
