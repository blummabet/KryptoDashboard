# CryptoEdge

Read-only Edge-Dashboard für Polymarket-Krypto-Märkte (Phase 1). Bewertet Poly-Preise gegen eine
faire Wahrscheinlichkeit aus **Spot + Deribit-IV** und zeigt Kontext-Signale (ETF, Funding, F&G …)
gedämpft daneben. **Kein Trading**, bis der Edge gegen die Referenz nachgewiesen ist.

## Struktur (pushbares Repo)

```
poly_core.py                 Polymarket-Kern: Gamma-Events + CLOB-Tiefe + fetch_market (Auflösung) + Filter
data_sources.py              Binance-Spot, Deribit-Index, Deribit Smile-IV (Strike/Verfall), Fear&Greed
fair_value.py                Europäisches Digital P(S_T ≥ K) + Fee-Modell (brutto/netto) — Herzstück, Familie C
build_markets.py             Phase-1-Pipeline: Poly-Tages-Schwellen → site/markets.json (read-only)
tracking.py                  Edge-Historie (append-only) → data/edge_history.jsonl
resolutions.py               Auflösungen aufgelöster Märkte → data/resolutions.json
clv.py                       Nordstern: Movement-CLV + Hit-Rate/PnL/Brier + Trends → site/clv.json
guards.py                    Guard-Batterie: deckt stille Fehler auf (Prob-/Row-/Referenz-Checks)
signals/base.py|registry.py  Signal-Interface + Anti-Korrelations-Combiner + Conviction
signals/context_signals.py   Konkrete Kontext-Signale (Fear&Greed) — Display, NICHT Trade-Edge
site/index.html + app.js     Modernes Dashboard: Trade-Edge-Tabelle + Kontext-Rail + Nordstern-KPIs
site/markets.json            Beispiel-Daten (Cron überschreibt)
tests/                       pytest-Suite (Fair Value, CLV, Guards, Signale, Parser)
.github/workflows/deploy-pages.yml   Cron-Build + Pages-Deploy + data/-Commit ([skip ci])
.github/workflows/tests.yml          CI: pytest bei jedem Push/PR
docs/gamma_krypto_katalog.md Live-Katalog der Poly-Krypto-Märkte (Tags, Serien, Markt-Typen, Fees)
```

Tests lokal: `pip install -r requirements-dev.txt && pytest -q` (Pipeline selbst nutzt nur die Stdlib).

## Auf GitHub bringen (du, via GitHub Desktop)

1. Neues, leeres **GitHub-Repo** anlegen (z.B. `crypto-edge`).
2. **Diesen Projektordner-Inhalt** committen & pushen (GitHub Desktop).
3. **Settings → Pages → Source: GitHub Actions** aktivieren.
4. Erster Lauf: **Actions → „Build & Deploy CryptoEdge" → Run workflow** (oder auf den Cron warten).
   Die Seite erscheint unter der Pages-URL; die Edge-Tabelle füllt sich aus `site/markets.json`.

## Status & nächste Schritte

- **Jetzt (1a):** Pipeline zieht echte Poly-Tages-Schwellenmärkte (`btc-multi-strikes-weekly`) →
  zeigt Poly-Preis + Liquidität. `fairProb`/`edge` bleiben **leer**, bis die IV-Quelle verdrahtet ist
  (bewusst kein Fake-Wert).
- **Als Nächstes (1b):** `data_sources.deribit_atm_iv()` an die Deribit-Optionskette hängen → faire
  Wkt. + Edge werden berechnet. Danach Kontext-Signale (Funding, F&G, ETF) als `signals/`-Module.
- **Offener Punkt:** Binance-Spot kann von US-basierten Actions-Runnern geblockt sein (Geoblock).
  Referenz muss aber Binance matchen (= Auflösungsquelle). Fallback `data-api.binance.vision` oder
  über den self-hosted Runner ziehen; Deribit-Index nur als Notnagel (Basis-Risiko).

## Nicht vergessen (Lehren aus dem Fußball-Repo)

- Edge IMMER gegen die echte Referenz (Spot/IV), nie Bauchgefühl → sonst Phantom-Edge.
- Barriere-Märkte (Familie D/E: „hit"/ATH) NICHT als Digital rechnen — One-Touch ≠ Digital.
- Taker-Fee (`crypto_fees_v2`) einpreisen, bevor ein Trade zählt — angezeigter Edge ist bis dahin BRUTTO.
- Nie aus leerer API-Antwort schließen „Poly hat es nicht" — erst live nachsehen.
- Nur Code committen; generierte Daten heilen sich über die Pipeline.
- Trading erst nach bewiesenem Edge, dry-run, Switches aus, self-hosted (Poly geoblockt).
```
