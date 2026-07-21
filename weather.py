#!/usr/bin/env python3
"""weather.py — Wetter-Pilot (read-only) → docs/weather.json.

DER ANDERE ANSATZ: nicht BTC vorhersagen (unmöglich), sondern Temperatur — die ist wissenschaftlich
treffsicher, und Polymarket bepreist sie oft schief. Kernidee (bewährt in der Meteorologie):
  1. Multi-Modell-Ensemble (ECMWF/GFS/ICON/JMA/GEM) am EXAKTEN Flughafen, auf den der Markt auflöst
     (nicht die Stadt — Seoul löst auf Incheon RKSI auf!).
  2. KALIBRIEREN: jedes Modell hat pro Station einen bekannten Bias → gegen die letzten Wochen
     Forecast-vs-Ist korrigieren. HIER sitzt der Edge, den kaum jemand macht.
  3. Aus dem kalibrierten Ensemble eine Verteilung der Tageshöchsttemperatur bauen und über die
     1°C-Buckets integrieren (Bucket "27°C" = Ist rundet auf 27 = Tmax in [26,5; 27,5)).
  4. Edge = unsere Bucket-Wkt. − Poly-Preis. Erst ab ~8pp interessant (überlebt die Taker-Fee).

EHRLICH: Pilot. Read-only, kein Geld. Der eigentliche Test ist CLV + Trefferquote gegen echte
Auflösungen über die nächsten Tage. Basis-Risiko: unsere Archiv-Temp muss die Wunderground-METAR-Zahl
treffen, auf die Poly auflöst — früh prüfen. Quelle Open-Meteo (frei, kein Key).
"""
from __future__ import annotations

import datetime
import json
import pathlib
import statistics
import urllib.parse
import urllib.request

import fair_value
import poly_core

OUT = pathlib.Path(__file__).parent / "docs" / "weather.json"
HIST = pathlib.Path(__file__).parent / "data" / "weather_history.jsonl"

FORECAST = "https://api.open-meteo.com/v1/forecast"
HIST_FC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "jma_seamless", "gem_seamless"]
CAL_DAYS = 21          # Kalibrier-Fenster (Forecast vs. Ist)
EDGE_TRADE_PP = 8.0    # ab hier interessant (> Taker-Fee)
SIGMA_FLOOR = 1.0      # Mindest-Unsicherheit in °C (Buckets sind 1°C breit)
_HEADERS = {"User-Agent": "CryptoEdge-Weather/1.0", "Accept": "application/json"}

# 6 Städte GEMISCHT: 'liquid' = westlich/gute Daten/mehr Bots · 'edge' = weniger Konkurrenz.
# Koordinaten = exakte Auflösungs-Flughafenstation (nicht Stadtzentrum!).
CITIES = {
    "NYC":        {"lat": 40.7772, "lon": -73.8726, "tz": "America/New_York", "station": "LaGuardia (KLGA)", "group": "liquid"},
    "London":     {"lat": 51.5053, "lon": 0.0553,   "tz": "Europe/London",    "station": "London City (EGLC)", "group": "liquid"},
    "Milan":      {"lat": 45.6306, "lon": 8.7281,    "tz": "Europe/Rome",      "station": "Malpensa (LIMC)", "group": "liquid"},
    "Seoul":      {"lat": 37.4602, "lon": 126.4407,  "tz": "Asia/Seoul",       "station": "Incheon (RKSI)", "group": "edge"},
    "Lucknow":    {"lat": 26.7606, "lon": 80.8893,   "tz": "Asia/Kolkata",     "station": "Chaudhary Charan Singh (VILK)", "group": "edge"},
    "Wellington": {"lat": -41.3272, "lon": 174.8053, "tz": "Pacific/Auckland", "station": "Wellington Intl (NZWN)", "group": "edge"},
}
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _get(url: str, params: dict, timeout: int = 20):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, safe=",")
    try:
        req = urllib.request.Request(f"{url}?{q}", headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠️ open-meteo {url.split('/')[-1]}: {e}")
        return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def slug_date(slug: str):
    """'highest-temperature-in-seoul-on-july-21-2026' → date(2026,7,21). None wenn nicht parsebar."""
    m = None
    parts = (slug or "").split("-")
    for i, p in enumerate(parts):
        if p in _MONTHS and i + 2 < len(parts) + 1:
            try:
                day = int(parts[i + 1]); year = int(parts[i + 2])
                return datetime.date(year, _MONTHS[p], day)
            except (ValueError, IndexError):
                return None
    return m


def bucket_range(label: str):
    """'27°C' → (26.5,27.5) · '21°C or below' → (-inf,21.5) · '30°C or above' → (29.5,inf).
    Auflösung auf GANZE Grad: Bucket X = Ist rundet auf X = Tmax in [X-0.5, X+0.5)."""
    low = (label or "").lower()
    digs = "".join(c if (c.isdigit() or c == "-") else " " for c in low).split()
    if not digs:
        return None
    x = int(digs[0])
    if "below" in low or "under" in low or "≤" in low or "or less" in low:
        return (float("-inf"), x + 0.5)
    if "above" in low or "over" in low or "≥" in low or "or more" in low or "+" in label:
        return (x - 0.5, float("inf"))
    return (x - 0.5, x + 0.5)


def bucket_prob(lo: float, hi: float, mean: float, sigma: float) -> float:
    """P(Tmax in [lo,hi)) unter Normal(mean, sigma)."""
    sigma = max(sigma, 0.1)
    plo = 0.0 if lo == float("-inf") else fair_value._norm_cdf((lo - mean) / sigma)
    phi = 1.0 if hi == float("inf") else fair_value._norm_cdf((hi - mean) / sigma)
    return max(0.0, min(1.0, phi - plo))


def _daily_on(resp: dict, date_iso: str, key: str):
    """Wert einer daily-Spalte am Zieldatum ziehen."""
    if not resp or "daily" not in resp:
        return None
    d = resp["daily"]
    times = d.get("time") or []
    if date_iso not in times:
        return None
    i = times.index(date_iso)
    col = d.get(key) or []
    return col[i] if i < len(col) else None


def ensemble_forecast(cfg: dict, date_iso: str):
    """Tmax-Forecast aller Modelle am Zieldatum → {model: value}, Mittel, Streuung."""
    resp = _get(FORECAST, {"latitude": cfg["lat"], "longitude": cfg["lon"], "timezone": cfg["tz"],
                           "daily": "temperature_2m_max", "start_date": date_iso, "end_date": date_iso,
                           "models": ",".join(MODELS)})
    if not resp:
        return None
    per = {}
    for m in MODELS:
        v = _daily_on(resp, date_iso, f"temperature_2m_max_{m}")
        if v is not None:
            per[m] = round(v, 2)
    if not per:
        return None
    vals = list(per.values())
    return {"models": per, "mean": round(_mean(vals), 2),
            "spread": round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0}


def calibrate(cfg: dict):
    """Bias + Reststreuung aus den letzten CAL_DAYS Tagen (Ensemble-Forecast vs. Archiv-Ist).
    bias = mean(Ist − Forecast) → auf den heutigen Forecast addieren. sigma = Std der Fehler."""
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=CAL_DAYS)).isoformat()
    end = (today - datetime.timedelta(days=1)).isoformat()
    fc = _get(HIST_FC, {"latitude": cfg["lat"], "longitude": cfg["lon"], "timezone": cfg["tz"],
                        "daily": "temperature_2m_max", "start_date": start, "end_date": end,
                        "models": ",".join(MODELS)})
    ar = _get(ARCHIVE, {"latitude": cfg["lat"], "longitude": cfg["lon"], "timezone": cfg["tz"],
                        "daily": "temperature_2m_max", "start_date": start, "end_date": end})
    if not fc or not ar or "daily" not in fc or "daily" not in ar:
        return {"bias": 0.0, "sigma": None, "n": 0}
    times = fc["daily"].get("time") or []
    errs = []
    actual_col = (ar["daily"].get("temperature_2m_max") or [])
    atimes = ar["daily"].get("time") or []
    for i, t in enumerate(times):
        # Ensemble-Mittel des Forecasts an Tag t
        fvals = [fc["daily"].get(f"temperature_2m_max_{m}", [None] * len(times))[i] for m in MODELS]
        fmean = _mean(fvals)
        if fmean is None or t not in atimes:
            continue
        a = actual_col[atimes.index(t)]
        if a is not None:
            errs.append(a - fmean)
    if len(errs) < 5:
        return {"bias": 0.0, "sigma": None, "n": len(errs)}
    bias = _mean(errs)
    sigma = statistics.pstdev(errs) if len(errs) > 1 else None
    return {"bias": round(bias, 2), "sigma": round(sigma, 2) if sigma else None, "n": len(errs)}


def _yes(m):
    try:
        return float(json.loads(m.get("outcomePrices") or "[]")[0])
    except Exception:
        return None


def build_city(city: str, cfg: dict, ev: dict, date_iso: str) -> dict | None:
    fc = ensemble_forecast(cfg, date_iso)
    if not fc:
        return None
    cal = calibrate(cfg)
    cal_mean = round(fc["mean"] + (cal["bias"] or 0.0), 2)
    # Unsicherheit: Kalibrier-Reststreuung ODER Modell-Spread, mind. SIGMA_FLOOR.
    sigma = max(cal.get("sigma") or fc["spread"] or SIGMA_FLOOR, SIGMA_FLOOR)

    buckets = []
    for m in (ev.get("markets") or []):
        if poly_core.is_derived_market(m.get("slug", "")):
            continue
        label = m.get("groupItemTitle") or m.get("question")
        rng = bucket_range(label)
        poly = _yes(m)
        if rng is None or poly is None:
            continue
        our = bucket_prob(rng[0], rng[1], cal_mean, sigma)
        edge = round((our - poly) * 100, 1)
        best_bid, best_ask = m.get("bestBid"), m.get("bestAsk")
        tradeable = abs(edge) >= EDGE_TRADE_PP and (best_ask is not None or best_bid is not None)
        buckets.append({
            "label": label, "conditionId": m.get("conditionId"),
            "ourProb": round(our, 4), "polyPrice": round(poly, 4), "edgePP": edge,
            "bestBid": best_bid, "bestAsk": best_ask,
            "dir": "kaufen" if edge > 0 else "meiden/verkaufen", "tradeable": tradeable,
        })
    if not buckets:
        return None
    buckets.sort(key=lambda b: bucket_range(b["label"])[0])
    our_mode = max(buckets, key=lambda b: b["ourProb"])["label"]
    mkt_mode = max(buckets, key=lambda b: b["polyPrice"])["label"]
    top = max(buckets, key=lambda b: abs(b["edgePP"]))
    return {
        "city": city, "group": cfg["group"], "station": cfg["station"], "date": date_iso,
        "slug": ev.get("slug"), "liquidityUSD": round(ev.get("liquidity") or 0),
        "vol24hUSD": round(ev.get("volume24hr") or 0),
        "ensembleMean": fc["mean"], "modelSpread": fc["spread"], "models": fc["models"],
        "bias": cal["bias"], "calDays": cal["n"], "calibratedMean": cal_mean, "sigma": round(sigma, 2),
        "ourMode": our_mode, "marketMode": mkt_mode, "modeMatch": our_mode == mkt_mode,
        "topEdge": {"label": top["label"], "edgePP": top["edgePP"], "dir": top["dir"], "tradeable": top["tradeable"]},
        "buckets": buckets,
    }


def build() -> dict:
    try:
        events = poly_core.gamma_events_by_tag("weather", limit=60) if hasattr(poly_core, "gamma_events_by_tag") else _weather_events()
    except Exception as e:
        print(f"  ⚠️ weather: Event-Fetch {e}")
        events = []
    by_city = {}
    for ev in events:
        title = ev.get("title") or ""
        if "temperature" not in title.lower():
            continue
        city = None
        for c in CITIES:
            if c.lower() in title.lower():
                city = c
                break
        if not city or city in by_city:
            continue
        by_city[city] = ev

    cities = []
    for city, cfg in CITIES.items():
        ev = by_city.get(city)
        if not ev:
            continue
        date = slug_date(ev.get("slug", "")) or _end_date(ev.get("endDate"))
        if not date:
            continue
        row = build_city(city, cfg, ev, date.isoformat())
        if row:
            cities.append(row)
    cities.sort(key=lambda c: -abs(c["topEdge"]["edgePP"]))

    edged = [c for c in cities if c["topEdge"]["tradeable"]]
    summary = {
        "citiesTracked": len(cities),
        "marketsWithEdge": len(edged),
        "bestEdgePP": cities[0]["topEdge"]["edgePP"] if cities else None,
        "avgAbsBias": round(_mean([abs(c["bias"]) for c in cities if c["bias"] is not None]) or 0, 2) if cities else None,
    }
    return {"summary": summary, "cities": cities}


def _weather_events(limit: int = 60):
    """Wetter-Events per Tag holen (falls poly_core keine Tag-Funktion hat)."""
    url = (f"{poly_core.GAMMA_EVENTS}?closed=false&active=true&tag_slug=weather"
           f"&limit={limit}&order=volume24hr&ascending=false")
    return poly_core._get_json(url) or []


def _end_date(iso):
    try:
        return datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00")).date()
    except Exception:
        return None


def _append_history(cities, ts):
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        for c in cities:
            for b in c["buckets"]:
                f.write(json.dumps({"ts": ts, "city": c["city"], "date": c["date"],
                                    "conditionId": b["conditionId"], "label": b["label"],
                                    "ourProb": b["ourProb"], "polyPrice": b["polyPrice"],
                                    "edgePP": b["edgePP"]}, ensure_ascii=False) + "\n")


def write():
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        data = build()
    except Exception as e:
        print(f"  ⚠️ weather: {e}")
        data = {"summary": {"citiesTracked": 0}, "cities": []}
    data["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["note"] = ("Wetter-Pilot (read-only): kalibriertes Multi-Modell-Ensemble am exakten "
                    "Auflösungs-Flughafen vs. Poly-1°C-Buckets. Edge ab 8pp interessant (überlebt Fee). "
                    "Der echte Test ist CLV + Trefferquote gegen Auflösungen — läuft über die Tage.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if data["cities"]:
        _append_history(data["cities"], ts)
    s = data["summary"]
    print(f"  Wetter: {s.get('citiesTracked', 0)} Städte, {s.get('marketsWithEdge', 0)} mit Edge≥8pp, "
          f"größter Edge {s.get('bestEdgePP')}pp, Ø|Bias| {s.get('avgAbsBias')}°C")


if __name__ == "__main__":
    write()
