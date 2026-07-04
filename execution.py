#!/usr/bin/env python3
"""execution.py — Order-Ausführungs-Schicht mit Sicherheits-Gates. DRY-RUN standardmäßig.

Alle Engines (Konvergenz, Arb, Maker) rufen NUR gegen diese Schnittstelle. Sie erzwingt die
Regeln für die GETEILTE Wallet + den GETEILTEN Runner (mit dem Betting-Bot), BEVOR etwas rausgeht:

  · crypto_kill_switch    — Not-Aus (ENV CRYPTO_KILL_SWITCH=1 oder data/crypto_kill_switch-Datei).
  · CRYPTO_DAILY_USDC_CAP — eigenes Tageslimit, getrennt vom Betting-Cap.
  · Live-Balance + RESERVE_FLOOR — frische USDC-Balance direkt vor jeder Order (nie gecacht); der
    gemeinsame Mindestbestand darf nie unterschritten werden.
  · Tages-Spend-Ledger (crash-sicher, write-then-rename) → zählt eigene Order-Exposure gegen den Cap.

Standard DRY_RUN=1 → es wird NUR geloggt, was platziert WÜRDE (kein echtes Geld, kein Key nötig).
Der echte CLOB-Client (portiert aus polymarket_bet.py) kommt als LiveExecutor — scharf NUR bei
DRY_RUN=0 + allen Gates grün + expliziter Bestätigung.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).parent
SPEND = ROOT / "data" / "crypto_spend.json"
LOG = ROOT / "data" / "exec_log.jsonl"
KILL_FILE = ROOT / "data" / "crypto_kill_switch"


def _env(k, d):
    return os.environ.get(k, d)


def dry_run() -> bool:
    return _env("DRY_RUN", "1") != "0"          # Standard: dry-run


def daily_cap() -> float:
    return float(_env("CRYPTO_DAILY_USDC_CAP", "12"))    # klein starten (~€11/Tag; Edge unbewiesen)


def reserve_floor() -> float:
    return float(_env("RESERVE_FLOOR_USDC", "1e12"))     # hoch = blockiert live, bis bewusst gesetzt


def kill_switch_active() -> bool:
    return _env("CRYPTO_KILL_SWITCH", "0") == "1" or KILL_FILE.exists()


@dataclass
class Order:
    side: str            # "BUY" | "SELL"
    token_id: str
    usdc: float          # BUY: Einsatz; SELL: geschätzter Erlös (für Exposure)
    label: str = ""
    source: str = ""     # "convergence" | "arb" | "maker"
    extra: dict = field(default_factory=dict)


class Executor:
    def place(self, order: "Order") -> dict:
        raise NotImplementedError


class DryRunExecutor(Executor):
    """Platziert NICHTS — loggt nur die beabsichtigte Order."""
    def place(self, order):
        return {"status": "DRY_RUN", "note": "würde platzieren"}


class LivePolyExecutor(Executor):
    """Scharfe Ausführung über den isolierten CLOB-Client (poly_clob.py). Wird von guarded_place
    NUR gewählt, wenn DRY_RUN=0 — davor greifen Kill-Switch/Cap/Reserve/Live-Balance-Gates."""
    def place(self, order):
        import poly_clob
        hint = order.extra.get("priceHint")
        if order.side == "BUY":
            return poly_clob.buy(order.token_id, order.usdc, hint)
        if order.side == "SELL":
            return poly_clob.sell(order.token_id, order.extra["size"], hint)
        return {"status": "failed", "error": f"unbekannte Seite {order.side}"}


def default_balance_reader():
    """Live-USDC-Balance über den CLOB-Client (nur scharf genutzt)."""
    import poly_clob
    return poly_clob.read_balance()


def _today():
    return datetime.date.today().isoformat()


def _load_spend():
    try:
        d = json.loads(SPEND.read_text(encoding="utf-8"))
        return d if d.get("date") == _today() else {"date": _today(), "spent": 0.0}
    except Exception:
        return {"date": _today(), "spent": 0.0}


def _save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)                            # atomar → kein halb-geschriebener State bei Absturz


def _log(rec):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def guarded_place(order: Order, executor: Executor | None = None, balance_reader=None) -> dict:
    """Alle Gates prüfen, dann platzieren (bzw. dry-run loggen). Gibt Ergebnis-Dict zurück."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reject(reason):
        rec = {"ts": now, "status": "REJECTED", "reason": reason, "order": order.__dict__}
        _log(rec)
        return rec

    # 1) Kill-Switch — Not-Aus vor allem anderen.
    if kill_switch_active():
        return reject("crypto_kill_switch aktiv")

    # 2) Tages-Cap (bisheriger Spend + diese Order).
    spend = _load_spend()
    if order.side == "BUY" and spend["spent"] + order.usdc > daily_cap():
        return reject(f"CRYPTO_DAILY_USDC_CAP überschritten ({spend['spent']}+{order.usdc}>{daily_cap()})")

    # 3) Live-Balance + Reserve — nur scharf; fail-safe: ohne lesbare Balance keine Order.
    if not dry_run() and order.side == "BUY":
        reader = balance_reader or default_balance_reader
        try:
            bal = reader()
        except Exception:
            bal = None
        if bal is None:
            return reject("Live-Balance nicht lesbar — Order blockiert (fail-safe)")
        if bal - order.usdc < reserve_floor():
            return reject(f"Reserve-Floor unterschritten ({bal}−{order.usdc}<{reserve_floor()})")

    # 4) Platzieren (oder dry-run).
    ex = executor or (DryRunExecutor() if dry_run() else LivePolyExecutor())
    try:
        res = ex.place(order)
    except Exception as e:
        return reject(f"Executor-Fehler: {e}")

    if order.side == "BUY":
        spend["spent"] = round(spend["spent"] + order.usdc, 2)
        _save_json(SPEND, spend)
    rec = {"ts": now, "status": res.get("status", "PLACED"), "order": order.__dict__, "result": res}
    _log(rec)
    return rec
