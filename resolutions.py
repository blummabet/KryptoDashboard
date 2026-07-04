#!/usr/bin/env python3
"""resolutions.py — Auflösungen getrackter Poly-Märkte nachziehen → data/resolutions.json.

Für jeden conditionId aus der Edge-Historie, der noch keine gespeicherte Auflösung hat, den Markt
per Slug holen; ist er closed + eindeutig aufgelöst (outcomePrices ["1","0"] oder ["0","1"]),
das Outcome speichern (1 = Yes gewonnen, 0 = No). Läuft im Actions-Cron (braucht Netz).

Verifiziert 2026-07-03: aufgelöster Markt hat closed=true, umaResolutionStatus="resolved",
outcomePrices ["0","1"] (hier: Yes verloren → 0).
"""
from __future__ import annotations

import datetime
import json
import pathlib

import poly_core
import tracking

RES = pathlib.Path(__file__).parent / "data" / "resolutions.json"


def load_resolutions() -> dict:
    if RES.exists():
        try:
            return json.loads(RES.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _outcome(m: dict | None):
    """1 = Yes gewonnen, 0 = No gewonnen, None = (noch) nicht eindeutig aufgelöst."""
    if not m or not m.get("closed"):
        return None
    try:
        yes = float(json.loads(m.get("outcomePrices") or "[]")[0])
    except Exception:
        return None
    if yes >= 0.99:
        return 1
    if yes <= 0.01:
        return 0
    return None


def update(history=None) -> dict:
    history = history if history is not None else tracking.load_history()
    res = load_resolutions()

    pending: dict[str, str] = {}
    for r in history:
        cid, slug = r.get("conditionId"), r.get("slug")
        if cid and slug and cid not in res and cid not in pending:
            pending[cid] = slug

    added = 0
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for cid, slug in pending.items():
        oc = _outcome(poly_core.fetch_market(slug))
        if oc is not None:
            res[cid] = {"outcome": oc, "slug": slug, "fetchedAt": now}
            added += 1

    RES.parent.mkdir(parents=True, exist_ok=True)
    RES.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"  Auflösungen: +{added} neu, {len(res)} gesamt")
    return res


if __name__ == "__main__":
    update()
