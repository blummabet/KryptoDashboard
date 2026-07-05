"""whale_signal.py — Smart-Money-/Whale-Flow als gedämpftes KONTEXT-Signal (zwei Flächen).

Quelle: PolymarketScan-API (pmscan.py). WEICHE Quelle → fließt NUR in die Anzeige-/Conviction-Fläche,
NIE in edgePP oder ein Trade-Gate. Die eigentliche Kante wird erst durch CLV-Kalibrierung gegen echte
Auflösungen bewiesen (build_markets snapshottet die Whale-Metriken dafür mit).

Bewusst KLEIN (≤1,5pp) und niedrige Confidence, unkalibriert. Feuert nur bei echtem Clustering
(≥ MIN_WALLETS unabhängige Wallets) — das ist laut PolymarketScan das belastbarste Muster
(3+ informierte Wallets gleiche Seite → Markt repreist in Folgetagen).

HINWEIS: Die exakte Richtungs-Zuordnung (Yes/No dieses Markts) ist gegen das Live-API-Schema noch
zu verifizieren, sobald ein Key gesetzt ist. Da das Signal display-only ist, kann ein falsches
Vorzeichen den Handel nicht beeinflussen — es beeinflusst nur die angezeigte Conviction.
"""
from __future__ import annotations

from .base import Signal, SignalResult

MIN_WALLETS = 3        # Clustering-Schwelle (PolymarketScan: 3+ unabhängige Wallets = Signal)
MAX_PP = 1.5           # Deckel: gedämpftes Kontext-Signal, nie groß
SCALE_USD = 50_000.0   # Netto-Flow, ab dem der Effekt gesättigt ist
CLUSTER_FULL = 5       # ab so vielen Wallets volle (aber weiter niedrige) Confidence


class WhaleFlowSignal(Signal):
    name = "whale_flow"
    family = "flow"     # Anti-Korrelation mit anderen Flow-Signalen (z.B. ETF)
    weight = 1.0

    def evaluate(self, ctx: dict) -> SignalResult:
        w = ctx.get("whale")
        if not w:
            return SignalResult(self.name, self.family, 0.0, silent=True, evidence="keine Whale-Daten")
        wallets = int(w.get("uniqueWallets") or 0)
        if wallets < MIN_WALLETS:
            return SignalResult(self.name, self.family, 0.0, silent=True,
                                evidence=f"nur {wallets} Wallets (<{MIN_WALLETS}) — kein Cluster")
        # Richtung: nach Outcome vorzeichenkorrigierter YES-Netto-Flow (binär), sonst Gesamt-Netto.
        net = w.get("yesNetUSD")
        if net is None:
            net = w.get("netFlowUSD") or 0.0
        sign = 1.0 if net > 0 else (-1.0 if net < 0 else 0.0)
        mag = min(abs(net) / SCALE_USD, 1.0)
        adj = round(sign * mag * MAX_PP, 2)
        conf = round(min(1.0, wallets / CLUSTER_FULL) * 0.6, 2)   # modest, unkalibriert
        side = w.get("dominantSide") or ("BUY" if net > 0 else "SELL")
        outc = w.get("dominantOutcome")
        ev = f"{wallets} Whale-Wallets, Net ${net:,.0f} ({side}" + (f" {outc}" if outc else "") + ")"
        if adj == 0.0:
            return SignalResult(self.name, self.family, 0.0, silent=True, evidence=ev + " — flach")
        return SignalResult(self.name, self.family, adj, confidence=conf, evidence=ev)
