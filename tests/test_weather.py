import datetime

import weather


def test_slug_date():
    assert weather.slug_date("highest-temperature-in-seoul-on-july-21-2026") == datetime.date(2026, 7, 21)
    assert weather.slug_date("highest-temperature-in-nyc-on-december-3-2026") == datetime.date(2026, 12, 3)
    assert weather.slug_date("garbage") is None


def test_bucket_range_plain_below_above():
    assert weather.bucket_range("27°C") == (26.5, 27.5)
    lo, hi = weather.bucket_range("21°C or below")
    assert lo == float("-inf") and hi == 21.5
    lo, hi = weather.bucket_range("30°C or above")
    assert lo == 29.5 and hi == float("inf")


def test_bucket_range_fahrenheit_and_ranges():
    # NYC-Format: 2°-Range-Buckets + offene Ränder in °F
    assert weather.bucket_range("72-73°F") == (71.5, 73.5)
    assert weather.bucket_range("88-89°F") == (87.5, 89.5)
    assert weather.bucket_range("71°F or below") == (float("-inf"), 71.5)
    assert weather.bucket_range("90°F or higher") == (89.5, float("inf"))


def test_bucket_range_junk_returns_none():
    assert weather.bucket_range("no numbers here") is None


def test_c_to_fahrenheit():
    assert weather._c_to("F", 25.0) == 77.0            # 25°C = 77°F
    assert weather._c_to("F", 1.0, is_delta=True) == 1.8   # Differenz: nur ×9/5
    assert weather._c_to("C", 25.0) == 25.0


def test_bucket_prob_peaks_at_mode():
    # Mean 27 → der 27er-Bucket muss die höchste Wkt. aller 1°-Buckets haben
    p27 = weather.bucket_prob(26.5, 27.5, 27.0, 1.5)
    p26 = weather.bucket_prob(25.5, 26.5, 27.0, 1.5)
    p28 = weather.bucket_prob(27.5, 28.5, 27.0, 1.5)
    assert p27 > p26 and p27 > p28


def test_bucket_probs_sum_to_one():
    # Volle Abdeckung (unten-offen … 1°-Buckets … oben-offen) muss sich zu 1 summieren
    mean, sigma = 26.3, 1.8
    total = weather.bucket_prob(float("-inf"), 21.5, mean, sigma)
    for x in range(22, 30):
        total += weather.bucket_prob(x - 0.5, x + 0.5, mean, sigma)
    total += weather.bucket_prob(29.5, float("inf"), mean, sigma)
    assert abs(total - 1.0) < 1e-9


def test_bucket_prob_bounds():
    assert weather.bucket_prob(float("-inf"), float("inf"), 25, 2) == 1.0
    assert 0.0 <= weather.bucket_prob(40.5, 41.5, 25, 2) <= 0.001   # weit weg → ~0


def _mkt(label, yes, bid=None, ask=None, cid=None):
    return {"groupItemTitle": label, "outcomePrices": f'["{yes}", "{1 - yes}"]',
            "bestBid": bid, "bestAsk": ask, "conditionId": cid or label, "slug": "will-x-" + label}


def test_build_city_edge_and_mode(monkeypatch):
    # Ensemble sagt 27°C fest; der Markt legt die Masse falsch auf 25°C → Edge auf 27 positiv
    monkeypatch.setattr(weather, "ensemble_forecast",
                        lambda cfg, d: {"models": {"ecmwf_ifs025": 27.0}, "mean": 27.0, "spread": 0.5})
    monkeypatch.setattr(weather, "calibrate", lambda cfg: {"bias": 0.0, "sigma": 1.2, "n": 20})
    ev = {"slug": "highest-temperature-in-seoul-on-july-21-2026", "liquidity": 1000, "volume24hr": 500,
          "markets": [_mkt("25°C", 0.60, bid=0.58, ask=0.62), _mkt("26°C", 0.20),
                      _mkt("27°C", 0.05, bid=0.04, ask=0.06), _mkt("28°C", 0.05)]}
    row = weather.build_city("Seoul", weather.CITIES["Seoul"], ev, "2026-07-21")
    assert row is not None
    assert row["ourMode"] == "27°C" and row["marketMode"] == "25°C" and row["modeMatch"] is False
    b27 = next(b for b in row["buckets"] if b["label"] == "27°C")
    assert b27["edgePP"] > 8 and b27["dir"] == "kaufen" and b27["tradeable"] is True
    b25 = next(b for b in row["buckets"] if b["label"] == "25°C")
    assert b25["edgePP"] < 0 and b25["dir"] == "meiden/verkaufen"


def test_detect_unit_from_labels_not_description():
    # Beschreibung nennt BEIDE Einheiten (Wunderground-Toggle) → darf NICHT auf 'F' reinfallen.
    toggle = "highest temperature ... in degrees Celsius ... toggle between Fahrenheit and Celsius ..."
    ev_c = {"markets": [{"groupItemTitle": "26°C", "description": toggle}]}
    ev_f = {"markets": [{"groupItemTitle": "72-73°F", "description": toggle}]}
    assert weather._detect_unit(ev_c) == "C"
    assert weather._detect_unit(ev_f) == "F"


def _fmkt(label, yes, desc, bid=None, ask=None):
    return {"groupItemTitle": label, "outcomePrices": f'["{yes}", "{1 - yes}"]',
            "bestBid": bid, "bestAsk": ask, "conditionId": label, "slug": "x-" + label,
            "description": desc}


def test_build_city_fahrenheit_conversion(monkeypatch):
    # Ensemble 25°C = 77°F. Markt in Fahrenheit → unser Modus muss der 76-77°F-Bucket sein,
    # NICHT ein °C-Artefakt. (Das war der −87pp-Bug.)
    monkeypatch.setattr(weather, "ensemble_forecast",
                        lambda cfg, d: {"models": {"gfs_seamless": 25.0}, "mean": 25.0, "spread": 0.5})
    monkeypatch.setattr(weather, "calibrate", lambda cfg: {"bias": 0.0, "sigma": 0.8, "n": 20})
    desc = "resolves ... in degrees Fahrenheit ... LaGuardia Airport Station"
    ev = {"slug": "highest-temperature-in-nyc-on-july-21-2026",
          "markets": [_fmkt("72-73°F", 0.05, desc), _fmkt("74-75°F", 0.10, desc),
                      _fmkt("76-77°F", 0.10, desc, bid=0.09, ask=0.11), _fmkt("78-79°F", 0.05, desc)]}
    row = weather.build_city("NYC", weather.CITIES["NYC"], ev, "2026-07-21")
    assert row["unit"] == "F"
    assert abs(row["calibratedMean"] - 77.0) < 0.01
    assert row["ourMode"] == "76-77°F"                 # 77°F fällt in [75.5, 77.5)
    b = next(x for x in row["buckets"] if x["label"] == "76-77°F")
    assert b["ourProb"] == max(x["ourProb"] for x in row["buckets"])   # höchste Masse hier


def test_build_city_bias_shifts_mean(monkeypatch):
    # Roh-Mittel 25, aber Station läuft +2° warm → kalibriert 27
    monkeypatch.setattr(weather, "ensemble_forecast",
                        lambda cfg, d: {"models": {"gfs_seamless": 25.0}, "mean": 25.0, "spread": 0.4})
    monkeypatch.setattr(weather, "calibrate", lambda cfg: {"bias": 2.0, "sigma": 1.0, "n": 21})
    ev = {"slug": "highest-temperature-in-nyc-on-july-21-2026", "markets": [_mkt("27°C", 0.1)]}
    row = weather.build_city("NYC", weather.CITIES["NYC"], ev, "2026-07-21")
    assert row["calibratedMean"] == 27.0 and row["bias"] == 2.0
