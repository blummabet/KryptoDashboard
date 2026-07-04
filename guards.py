#!/usr/bin/env python3
"""guards.py — Guard-Batterie: deckt stille Fehler auf, statt falsche Zahlen durchzuwinken.

Muster aus dem Fußball-Repo: lieber laut warnen/scheitern als eine Phantom-Zahl anzeigen.
Die Pipeline ruft `audit_rows` vor dem Schreiben — Warnungen werden geloggt (Daten heilen sich
über den Cron), harte Verletzungen kann der Aufrufer eskalieren.
"""
from __future__ import annotations

import math


class GuardError(Exception):
    """Harte Verletzung — sollte nie passieren, wenn doch: sichtbar scheitern."""


def _is_num(x):
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def check_prob(x, label="prob"):
    """Wkt. muss in [0,1] und keine NaN sein. None ist erlaubt (noch nicht gerechnet)."""
    if x is None:
        return None
    if not _is_num(x) or not (0.0 <= x <= 1.0):
        raise GuardError(f"{label} außerhalb [0,1] oder NaN: {x!r}")
    return x


def check_row(row: dict) -> list[str]:
    """Validiert eine Markt-Zeile. Gibt Liste von Warnungen zurück (leer = ok)."""
    w = []
    p, f, e = row.get("polyPrice"), row.get("fairProb"), row.get("edgePP")
    if p is None or not _is_num(p) or not (0.0 <= p <= 1.0):
        w.append(f"polyPrice ungültig: {p!r}")
    if f is not None and (not _is_num(f) or not (0.0 <= f <= 1.0)):
        w.append(f"fairProb ungültig: {f!r}")
    s = row.get("strike")
    if s is not None and (not _is_num(s) or s <= 0):
        w.append(f"strike ungültig: {s!r}")
    if e is not None and (not _is_num(e) or abs(e) > 100):
        w.append(f"edge unrealistisch: {e!r}")
    iv = row.get("ivPct")
    if iv is not None and (not _is_num(iv) or not (0 < iv < 500)):
        w.append(f"IV unplausibel: {iv!r}")
    if row.get("direction") not in (None, "above", "below"):
        w.append(f"direction unbekannt: {row.get('direction')!r}")
    return w


def audit_rows(rows) -> dict[str, list[str]]:
    """Sammelt Warnungen über alle Zeilen: {slug/id: [warnungen]}. Leer = alles sauber."""
    issues = {}
    for r in rows:
        w = check_row(r)
        if w:
            issues[r.get("slug") or r.get("conditionId") or "?"] = w
    return issues


def check_reference(spot, iv=None) -> list[str]:
    """Referenz-Sanity: Spot plausibel, IV (falls da) plausibel."""
    w = []
    if spot is not None and (not _is_num(spot) or spot <= 0):
        w.append(f"spot ungültig: {spot!r}")
    if iv is not None and (not _is_num(iv) or not (0 < iv < 5)):
        w.append(f"iv (dez.) unplausibel: {iv!r}")
    return w
