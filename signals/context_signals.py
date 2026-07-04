"""context_signals.py — konkrete Kontext-Signale (Display/Regime, NICHT Trade-Edge).

WICHTIG (zwei Flächen): diese Signale fließen in die ANZEIGE-Fläche (Kontext/Conviction),
NIE in edgePP. Der Trade-Edge bleibt strikt Poly-Preis vs. faire Wkt. (Deribit-IV + Spot).
So vermeiden wir den Phantom-Edge aus weichen Quellen.
"""
from __future__ import annotations

from .base import Signal, SignalResult


class FearGreedSignal(Signal):
    """Crypto Fear & Greed als gedämpftes Regime-Signal. Bewusst klein (≤1pp) und nur Anzeige."""
    name = "fear_greed"
    family = "sentiment"
    weight = 1.0

    def evaluate(self, ctx: dict) -> SignalResult:
        fg = (ctx.get("context") or {}).get("fearGreed")
        if not fg or fg.get("value") is None:
            return SignalResult(self.name, self.family, 0.0, silent=True, evidence="F&G n/a")
        v = fg["value"]
        cls = fg.get("classification") or ""
        # Extreme Angst = leicht konträr-bullish, extreme Gier = leicht bearish. Max ±1pp, low conf.
        adj = round((50 - v) / 50.0 * 1.0, 2)
        return SignalResult(self.name, self.family, adj, confidence=0.5,
                            evidence=f"F&G {v} ({cls})")
