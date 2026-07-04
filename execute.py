#!/usr/bin/env python3
"""execute.py — Runner-Entry (läuft auf dem self-hosted Mac, Wohn-IP).

Liest data/intents.json (von paper_engine in der Cloud-Pipeline geschrieben) und schleust jede
beabsichtigte Order durch execution.guarded_place. Standard DRY_RUN=1 → loggt nur, platziert nichts.
Idempotent: bereits verarbeitete Intent-IDs (aus data/exec_log.jsonl) werden übersprungen, damit ein
zweiter Lauf auf denselben Intents NICHTS doppelt platziert.

Isolation: berührt KEINE Betting-Dateien; eigener State (data/exec_log.jsonl, data/crypto_spend.json).
Order-Placement geht NUR von der Wohn-IP (Datacenter geoblockt) → dieser Job läuft self-hosted.
"""
from __future__ import annotations

import json
import pathlib

import execution
from execution import Order

INTENTS = pathlib.Path(__file__).parent / "data" / "intents.json"


def _processed_ids():
    ids = set()
    if execution.LOG.exists():
        for line in execution.LOG.read_text(encoding="utf-8").splitlines():
            try:
                extra = (json.loads(line).get("order") or {}).get("extra") or {}
                if extra.get("id"):
                    ids.add(extra["id"])
            except Exception:
                pass
    return ids


def _load_intents():
    try:
        return json.loads(INTENTS.read_text(encoding="utf-8")).get("intents", [])
    except Exception:
        return []


def run():
    intents = _load_intents()
    done = _processed_ids()
    mode = "DRY-RUN" if execution.dry_run() else "LIVE"
    print(f"execute [{mode}] — {len(intents)} Intent(s), Cap ${execution.daily_cap()}, "
          f"kill_switch={'AN' if execution.kill_switch_active() else 'aus'}")

    placed = skipped = rejected = 0
    for it in intents:
        if it.get("id") in done:
            skipped += 1
            continue
        if not it.get("tokenId"):
            print(f"  ⚠️ ohne tokenId übersprungen: {it.get('label')}")
            skipped += 1
            continue
        order = Order(
            side=it["side"], token_id=it["tokenId"], usdc=float(it.get("usdc") or 0.0),
            label=it.get("label", ""), source=it.get("source", ""),
            extra={"id": it["id"], "priceHint": it.get("priceHint"), "size": it.get("size")},
        )
        res = execution.guarded_place(order)
        st = res.get("status")
        if st == "REJECTED":
            rejected += 1
            print(f"  ✗ abgelehnt ({res.get('reason')}): {order.label}")
        else:
            placed += 1
            print(f"  · {st}: {order.side} {order.label}")

    # Jeder Lauf hinterlässt eine sichtbare Zusammenfassung (auch bei 0 Intents) — inkl. Kill-Switch.
    execution._log({
        "ts": execution.datetime.datetime.now(execution.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "run", "mode": mode, "intents": len(intents),
        "placed": placed, "skipped": skipped, "rejected": rejected,
        "killSwitch": execution.kill_switch_active(),
    })
    print(f"  → {placed} verarbeitet, {skipped} übersprungen, {rejected} abgelehnt")


if __name__ == "__main__":
    run()
