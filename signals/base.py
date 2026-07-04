"""base.py — Signal-Interface (portiert aus dem BetEdge-Repo, domänen-agnostisch).

Jedes Kontext-Signal (ETF, Funding, F&G, Orderbook …) erbt von Signal und liefert ein
SignalResult. Roh-Empfehlung in Prozentpunkten; der Combiner (registry.py) verrechnet sie
anti-korreliert + gewichtet. Ein still fehlerhaftes Signal → Guard → silent (nie crashen)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SignalResult:
    name: str
    family: str            # Anti-Korrelations-Gruppe (z.B. "vola", "flow", "sentiment", "microstructure")
    adj_pp: float          # Roh-Empfehlung in Prozentpunkten (+ stützt Pick, − dagegen)
    confidence: float = 1.0
    evidence: str = ""     # menschenlesbare Begründung (für Card/Anzeige-Fläche)
    silent: bool = False   # True = feuert nicht (kein Signal, oder Guard ausgelöst)


class Signal(ABC):
    name: str = "signal"
    family: str = "misc"
    weight: float = 1.0    # Bayesian-Gewicht, lernt später aus realisierten Auflösungen

    @abstractmethod
    def evaluate(self, ctx: dict) -> SignalResult:
        """ctx enthält die aktuellen Daten (spot, iv, poly-markt, kontext-quellen).
        Muss IMMER ein SignalResult liefern — Fehler abfangen und silent zurückgeben."""
        ...
