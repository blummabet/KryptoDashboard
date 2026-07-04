"""registry.py — Signal-Registry + Anti-Korrelations-Kombinierer (portiert, generisch).

Anti-Korrelation (Fußball-Lehre): Signale derselben Familie zählen nicht mehrfach voll.
Stärkstes Signal der Familie voll gewertet, der Rest auf DAMP gedämpft — sonst wird derselbe
Faktor doppelt gezählt (z.B. Vola-Regime aus IV UND realized vol).

Zwei Flächen: Der engine_adj_pp/conviction ist die ANZEIGE-Fläche (Cards/Kontext).
Der Trade-Edge bleibt getrennt (Poly vs faire Wkt.) — der Combiner steuert KEINE Order.
"""
from __future__ import annotations

from .base import Signal, SignalResult

DAMP = 0.40  # Nicht-stärkste Familienmitglieder auf 40%


class SignalRegistry:
    def __init__(self):
        self._signals: list[Signal] = []

    def register(self, sig: Signal) -> Signal:
        self._signals.append(sig)
        return sig

    def evaluate_all(self, ctx: dict) -> list[SignalResult]:
        out: list[SignalResult] = []
        for s in self._signals:
            try:
                out.append(s.evaluate(ctx))
            except Exception as e:  # Guard-Batterie: stiller Fehler → silent, nie crashen
                out.append(SignalResult(s.name, s.family, 0.0, silent=True, evidence=f"guard: {e}"))
        return out


def combine(results: list[SignalResult], weights: dict | None = None) -> dict:
    """Anti-Korrelations-gewichtete Summe der Adjustments + Conviction-Score 0–10."""
    weights = weights or {}
    active = [r for r in results if not r.silent and abs(r.adj_pp) > 1e-9]

    fam: dict[str, list[SignalResult]] = {}
    for r in active:
        fam.setdefault(r.family, []).append(r)

    total = 0.0
    for members in fam.values():
        members.sort(key=lambda r: abs(r.adj_pp * r.confidence), reverse=True)
        for i, r in enumerate(members):
            w = weights.get(r.name, 1.0) * r.confidence * (1.0 if i == 0 else DAMP)
            total += r.adj_pp * w

    # Conviction: Anzahl unabhängiger Familien, die den Pick stützen, + Netto-Stärke.
    support = sum(1 for members in fam.values() if sum(r.adj_pp for r in members) > 0)
    conviction = max(0, min(10, round(support * 2 + total)))

    return {
        "engine_adj_pp": round(total, 2),
        "conviction": conviction,
        "families": len(fam),
        "active": len(active),
    }
