#!/usr/bin/env python3
"""fair_value.py — Faire Wahrscheinlichkeit aus Spot + Vola (Phase-1-Kern, das Herzstück).

Familie C (Tages-Schwellen, z.B. "BTC über $110k on <Datum>"): europäisches Digital P(S_T ≥ K).
Auflösung dieser Märkte = Binance BTC/USDT Close um 12:00 ET → Referenz-Spot MUSS Binance sein.

Disziplin (nicht verhandelbar):
  · Edge NUR gegen echte Referenz (Spot + IV) messen — nie Bauchgefühl (Phantom-Edge).
  · Barriere-Märkte (Familie D/E: "hit"/ATH) NICHT hiermit rechnen — One-Touch ≠ Digital.
  · IV-Quelle (Deribit) ist ein bewusster Seam: erst live prüfen, dann verdrahten.
"""
from __future__ import annotations

import math

_SQRT2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def digital_above(spot, strike, sigma, t_years, r=0.0):
    """Risk-neutrale Wkt. S_T ≥ strike (lognormal, europäisch).
    sigma = annualisierte IV (dez.), t_years = Restlaufzeit in Jahren. None wenn Inputs unbrauchbar."""
    if not spot or not strike or not sigma or not t_years or sigma <= 0 or t_years <= 0:
        return None
    d2 = (math.log(spot / strike) + (r - 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    return _norm_cdf(d2)


def digital_below(spot, strike, sigma, t_years, r=0.0):
    p = digital_above(spot, strike, sigma, t_years, r)
    return None if p is None else 1.0 - p


def one_touch(spot, barrier, sigma, t_years, r=0.0):
    """Risk-neutrale Wkt., dass der Kurs die Barriere in [0,T] MINDESTENS EINMAL berührt
    (One-Touch, kontinuierlich ≈ 1m-Candles). Für Familie D/E (hit/dip/ATH) — NICHT als Digital.
    Auto-Richtung: barrier > spot = up-Touch, barrier < spot = down-Touch. Bei OFFENEN Märkten ist
    der Kurs noch auf der nicht-berührten Seite, daher folgt die Richtung sauber aus barrier vs spot.
    First-Passage-Formel für arithmetische BM (ν = r − σ²/2)."""
    if not spot or not barrier or not sigma or not t_years or sigma <= 0 or t_years <= 0:
        return None
    nu = r - 0.5 * sigma * sigma
    s = sigma * math.sqrt(t_years)
    a = math.log(barrier / spot)
    factor = math.exp(2 * nu * a / (sigma * sigma))   # = spot/barrier bei r=0
    if a >= 0:                                          # up-Barriere
        p = _norm_cdf((-a + nu * t_years) / s) + factor * _norm_cdf((-a - nu * t_years) / s)
    else:                                              # down-Barriere
        p = _norm_cdf((a - nu * t_years) / s) + factor * _norm_cdf((a + nu * t_years) / s)
    return max(0.0, min(1.0, p))


# Taker-Fee der Krypto-Märkte: feeType crypto_fees_v2, rate 0.07, taker-only (im Markt-Objekt
# verifiziert). Exakte Formel noch nicht am echten Fill bestätigt → wir nutzen ein KONSERVATIVES
# Modell fee = rate·min(p, 1−p): am Geld am teuersten, an den Rändern günstiger. Konservativ =
# lieber Edge untertreiben als Phantom-Edge schönrechnen. TODO: am echten Fill verifizieren.
FEE_RATE = 0.07


def estimated_fee_pp(price, rate=FEE_RATE):
    """Geschätzte Taker-Fee in Prozentpunkten. 0 wenn kein Preis."""
    if price is None:
        return 0.0
    return rate * min(price, 1.0 - price) * 100.0


def gross_edge_pp(fair_prob, poly_price):
    """Brutto-Edge in pp = (fair − poly)·100. None wenn Fair fehlt."""
    if fair_prob is None or poly_price is None:
        return None
    return round((fair_prob - poly_price) * 100.0, 2)


def net_edge_pp(fair_prob, poly_price, rate=FEE_RATE):
    """Netto-Edge in pp = Brutto − geschätzte Taker-Fee. Konservativ. None wenn Fair fehlt."""
    g = gross_edge_pp(fair_prob, poly_price)
    if g is None:
        return None
    return round(g - estimated_fee_pp(poly_price, rate), 2)
