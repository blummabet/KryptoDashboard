#!/usr/bin/env python3
"""tracking.py — Edge-Historie (append-only) für die CLV-Messung (Nordstern).

Jeder Pipeline-Lauf hängt einen Snapshot pro Markt an data/edge_history.jsonl.
Persistenz: der Actions-Workflow committet data/ mit [skip ci] zurück — die Historie ist echte
Zeitreihe und kann sich NICHT von selbst heilen (anders als markets.json, das regenerierbar ist).
"""
from __future__ import annotations

import datetime
import json
import pathlib

HIST = pathlib.Path(__file__).parent / "data" / "edge_history.jsonl"

# Felder pro Snapshot — genau die, die wir für Edge-Verlauf + CLV brauchen.
FIELDS = ("conditionId", "slug", "asset", "market", "strike", "direction", "endDate",
          "polyPrice", "fairProb", "edgePP", "edgeGrossPP", "ivPct", "liquidityUSD")


def append_snapshots(rows, ts=None):
    """Snapshot pro Markt anhängen. Gibt den Zeitstempel des Laufs zurück."""
    ts = ts or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        for r in rows:
            rec = {"ts": ts}
            rec.update({k: r.get(k) for k in FIELDS})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return ts


def load_history():
    """Alle Snapshots als Liste von Dicts (leer, wenn noch keine Historie)."""
    if not HIST.exists():
        return []
    out = []
    for line in HIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out
