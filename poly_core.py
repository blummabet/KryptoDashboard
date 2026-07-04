#!/usr/bin/env python3
"""
poly_core.py — Wiederverwendbarer Polymarket-Kern (fußball-agnostisch, aus dem BetEdge-Repo extrahiert).

Enthält NUR die generischen, hart erkämpften Bausteine:
  · gamma_events(series_slug)  — offene Events einer Serie holen (mit den richtigen Query-Params)
  · is_derived_market(slug)    — Kind-/Spezialmärkte aussortieren (Allowlist statt Blockliste)
  · fetch_clob_depth(token_id) — Top-of-Book Bid/Ask + Liquidität aus dem CLOB

KEINE Domänenlogik (kein Fußball, kein Krypto) — das kommt im aufrufenden Projekt drauf.

LEHREN, die hier schon eingebaut sind (teuer gelernt):
  1. `closed=false&order=startDate&ascending=false&limit=300` — sonst schneidet limit=100 die
     NEUESTEN Märkte einer laufenden Serie ab (die Serie hat oft >100 Events).
  2. Kind-/Spezialmärkte NIE als Hauptmarkt parsen → Allowlist.
     ⚠️ Krypto-Slugs sehen anders aus (Unix-Timestamp oder Text-Datum, NICHT ISO YYYY-MM-DD) —
        _DERIVED_SLUG_RE greift bei Krypto praktisch nie. Bei Serien-Queries ist das ok, da jedes
        Event bereits der gewünschte Markt ist; die echte Filterarbeit ist: bei Multi-Strike-Events
        durch markets[] iterieren und hide-from-new-Märkte ausschließen (macht der Aufrufer).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

GAMMA_EVENTS  = "https://gamma-api.polymarket.com/events"
GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK     = "https://clob.polymarket.com/books?token_id={token_id}"

# Abgeleiteter Markt = ISO-Datum + Suffix. Bei Krypto meist irrelevant (siehe Docstring).
_DERIVED_SLUG_RE = re.compile(r"-\d{4}-\d{2}-\d{2}-")

_HEADERS = {"User-Agent": "CryptoEdge/1.0", "Accept": "application/json"}


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} fetching {url}")
        raise
    except urllib.error.URLError as e:
        print(f"  URL error: {e.reason}")
        raise


def gamma_events(series_slug: str, limit: int = 300, closed: bool = False) -> list:
    """Offene Events einer Polymarket-Serie holen — neueste zuerst, mit Headroom.
    Gibt die rohe Event-Liste zurück (Filtern/Parsen macht der Aufrufer).
    Verifiziert 2026-07-03: series_slug=<slug> filtert korrekt (z.B. btc-up-or-down-5m)."""
    url = (f"{GAMMA_EVENTS}?series_slug={series_slug}"
           f"&limit={limit}&active=true&closed={'true' if closed else 'false'}"
           f"&order=startDate&ascending=false")
    events = _get_json(url)
    print(f"  {len(events)} Events aus series_slug={series_slug}")
    return events


def fetch_market(slug: str) -> dict | None:
    """Einen einzelnen Markt per Slug holen (u.a. für Auflösungs-Check). None bei Fehler/leer."""
    if not slug:
        return None
    try:
        d = _get_json(f"{GAMMA_MARKETS}?slug={slug}&limit=1")
        return d[0] if d else None
    except Exception as e:
        print(f"  ⚠️ fetch_market({slug}): {e}")
        return None


def is_derived_market(slug: str) -> bool:
    """True = Kind-/Spezialmarkt (nicht der Hauptmarkt) → beim Parsen überspringen."""
    return bool(_DERIVED_SLUG_RE.search(slug or ""))


def has_hide_tag(obj: dict) -> bool:
    """True = Markt/Event trägt 'hide-from-new' → aus der Anzeige/Allowlist raus."""
    for t in (obj.get("tags") or []):
        if (t.get("slug") or "") == "hide-from-new":
            return True
    return False


def fetch_clob_depth(token_id: str) -> dict | None:
    """Top-of-Book (bester Bid/Ask + Spread + Liquidität) aus dem Polymarket-CLOB.
    Nur für relevante Märkte aufrufen (API-Last). None bei Fehler/leerem Buch."""
    if not token_id:
        return None
    try:
        data = _get_json(CLOB_BOOK.format(token_id=token_id), timeout=8)
        bids, asks = data.get("bids") or [], data.get("asks") or []
        if not bids or not asks:
            return None
        best_bid, best_ask = float(bids[0]["price"]), float(asks[0]["price"])
        bid_liq  = float(bids[0].get("size", 0))
        ask_liq  = float(asks[0].get("size", 0))
        return {
            "bid":       round(best_bid, 4),
            "ask":       round(best_ask, 4),
            "mid":       round((best_bid + best_ask) / 2, 4),
            "spreadPP":  round((best_ask - best_bid) * 100, 1),
            "topLiqUSD": round(bid_liq + ask_liq, 0),
        }
    except Exception as e:
        print(f"  ⚠️  CLOB-Tiefe fehlgeschlagen ({str(token_id)[:12]}…): {e}")
        return None


if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "btc-up-or-down-5m"
    evs = gamma_events(slug, limit=10)
    for e in evs[:10]:
        s = e.get("slug", "")
        print(("  derived" if is_derived_market(s) else "  BASIS  "), s, "|", e.get("title"))
