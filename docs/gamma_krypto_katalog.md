# Polymarket Gamma-API — Krypto-Markt-Katalog

**Stand:** 2026-07-03 · Live gegen `gamma-api.polymarket.com` geprüft (read-only), nichts geraten.
Quelle für Schritt 2 im Phasenplan: Markt-Typen katalogisieren, Tags/Slugs für BTC/ETH/SOL
verifizieren, Feld-Mapping + Fair-Value-Implikationen für den Fetcher festhalten.

---

## 0. Kernbefunde (TL;DR)

1. **Fünf Markt-Familien** für die großen Kryptos, in zwei modellrelevante Klassen:
   - **Europäische Digitals** (Preis zu einem festen Zeitpunkt ≥/≤ Strike) → sauber mit Black-Scholes + Deribit-IV bepreisbar. Das ist unser **primäres Fair-Value-Ziel**.
   - **One-Touch-Barrieren** (irgendwann im Zeitraum berührt) → brauchen **Barrier-Pricing**, NICHT als Digital rechnen (sonst systematischer Phantom-Edge).
2. **Neu vs. Fußball: Es gibt Fees.** Alle Krypto-Märkte tragen `feeType: crypto_fees_v2` (Rate 0.07, taker-only, Rebate 0.2). Das hebt den Edge-Floor — muss in die Edge-Rechnung.
3. **Resolution-Quellen unterscheiden sich je Familie** (Chainlink Data Streams vs. Binance CEX-Candles). Unsere Spot/IV-Referenz muss zur jeweiligen Resolution-Quelle passen, sonst Basis-Risiko = Phantom-Edge.
4. **Alle Märkte `restricted: true`** → geoblockt. Bestätigt: Live-Trading nur über self-hosted Runner.
5. **`clobTokenIds` sind überall vorhanden** → Order-Book-Tiefe via CLOB portierbar wie im Fußball-Repo.
6. Wichtige Ordering-Falle bestätigt: `order=startDate&ascending=false` liefert die neuesten Märkte; ohne fehlen sie.

---

## 1. Datenzugriff

**Basis:** `https://gamma-api.polymarket.com`

| Endpoint | Zweck | Hinweis |
|---|---|---|
| `/events` | Events inkl. verschachtelter `markets[]`, `series[]`, `tags[]` | Für Multi-Strike-Events **sehr groß** (60–82 KB/Response) — Feld-Selektion nicht unterstützt |
| `/markets` | Flache Einzelmärkte (je Strike ein Objekt) | Deutlich schlanker; für gezielte Struktur-Checks bevorzugen |
| `/series` | Serien-Metadaten (recurrence, volume, slug) | Leichtgewichtig, gut für Serien-Katalog |

**Query-Parameter, die wir brauchen:**
- `closed=false` — nur offene Märkte
- `order=startDate&ascending=false` — neueste zuerst (Pflicht, sonst fehlen frische Märkte)
- `order=volume24hr` / `order=volumeNum` — nach Liquidität/Aktivität sortieren
- `tag_id=` bzw. `tag_slug=` — nach Asset/Kategorie filtern
- `exclude_tag_id=` — **funktioniert** (z. B. Up/Down `102127` rausfiltern, um Threshold-Märkte zu isolieren)
- `limit=`, `offset=` — Paginierung

> **Fetcher-Warnung:** Der Event-Endpoint sprengt bei Multi-Strike-Events das Token-Limit einer einzelnen Antwort. Der Python-Fetcher soll roh nach JSON-Datei streamen und dann parsen — nie die ganze Event-Antwort in einen Kontext laden.

---

## 2. Tag-Katalog (verifiziert)

**Asset-Tags:**

| Asset | Slug | Tag-ID |
|---|---|---|
| Bitcoin | `bitcoin` | 235 |
| Ethereum | `ethereum` | 39 |
| Solana | `solana` | 818 |
| XRP | `xrp` | 101267 |
| Dogecoin | `dogecoin` | 100178 |
| BNB | `bnb` | 102716 |
| Hyperliquid | `hype` | 102331 |

**Kategorie-/Struktur-Tags:**

| Label | Slug | Tag-ID | Rolle |
|---|---|---|---|
| Crypto | `crypto` | 21 | Oberkategorie |
| Crypto Prices | `crypto-prices` | 1312 | Preis-Märkte (forceShow) — guter Sammel-Filter |
| Up or Down | `up-or-down` | 102127 | Up/Down-Familie; zum Ausschluss von Threshold-Märkten nutzen |
| Recurring | `recurring` | 101757 | Rollierende Serien |
| 5M / 15M / 1H | `5M` / `15M` / `1H` | 102892 / 102467 / 102175 | Zeithorizont-Bucket |
| Hide From New | `hide-from-new` | 102169 | **Allowlist-Filter:** markiert Spezial-/Kindmärkte zum Ausblenden |

---

## 3. Markt-Typ-Taxonomie (5 Familien)

### A) Up/Down — kurz (5m, 15m)
- **Frage:** „<Asset> Up or Down — <Zeitfenster>". Binär `["Up","Down"]`.
- **Auflösung:** `price_end ≥ price_start` über das Fenster, **Chainlink Data Stream** (`data.chain.link/streams/<asset>-usd`).
- **Serien:** `btc-up-or-down-5m` (10684), `btc-up-or-down-15m` (10192), `eth-up-or-down-15m` (10191), `sol-up-or-down-5m` (10686), analog DOGE/XRP/BNB/HYPE.
- **Liquidität:** Höchste im ganzen Segment — **BTC 5m ≈ 23,3 Mio. USD/24h**, BTC 15m ≈ 3,1 Mio.
- **Modell:** Europäisches Digital **am Geld** (K = S₀). P ≈ 0,5 + winziger IV-/Drift-Term. Edge = Poly-Preis vs. 0,5±. Referenz-Vola aus Deribit-IV (kürzeste Laufzeit).

### B) Up/Down — stündlich
- **Auflösung:** Binance `BTC/USDT` **1H-Candle Open vs. Close**, **UMA-Oracle** (`umaBond` 500, `customLiveness` 600).
- **Serie:** `btc-up-or-down-hourly` (10114), recurrence `hourly`. BTC ≈ 1,3 Mio. USD/24h.
- **Modell:** Europäisches Digital am Geld über 1h; Referenz = Binance-Spot (nicht Chainlink!).

### C) Daily „above $X" (Multi-Strike, europäisch) — **primäres Fair-Value-Ziel**
- **Event:** „Bitcoin above ___ on <Datum>?" · **Serie `btc-multi-strikes-weekly` (ID 45, recurrence daily)**.
- **Frage je Strike:** „Will the price of Bitcoin be above $70,000 on July 4?" · `["Yes","No"]`, `groupItemThreshold` = Anzahl Strikes.
- **Auflösung:** Binance `BTC/USDT` **1m-Candle Close um 12:00 ET** > Strike. **Fester Zeitpunkt → echtes europäisches Digital.**
- **Extra-Signal:** Serie 45 trägt `pythTokenID` und `cgAssetName: "bitcoin"` — Polymarket referenziert intern Pyth + CoinGecko.
- **Modell:** Black-Scholes-Digital `P(S_T > K)` mit Deribit-IV. **Sauberste, direkteste Poly-vs-Fair-Kante** → hier zuerst bauen.

### D) Monthly „hit price" (Multi-Strike, One-Touch-Barriere)
- **Event:** „What price will <Asset> hit in <Monat>?" · Serien `bitcoin-hit-price-monthly`, `ethereum-hit-price-monthly` (10017), `solana-hit-price-monthly` (10032), recurrence `monthly`.
- **Frage je Strike:** „Will Ethereum reach $6,000 by December 31, 2026?" (up) bzw. „Will Solana dip to $40 in July?" (down).
- **Auflösung:** „**immediately resolve to Yes if any** Binance 1m-Candle **High ≥ Strike**" (up) / **Low ≤ Strike** (down). **Berührung irgendwann im Zeitraum → One-Touch.**
- **Modell:** **One-Touch-Barrier-Wahrscheinlichkeit** (bei weiten Strikes grob ~2× des europäischen Digitals). **NICHT als Digital bepreisen** — das wäre ein eingebauter Phantom-Edge.

### E) „All-time high by <Datum>?"
- **Event:** „<Asset> all time high by ___?" (`ethereum-all-time-high-by`, 107009).
- **Auflösung:** Binance 1m-High übersteigt bisheriges ATH → One-Touch gegen laufendes Maximum.
- **Modell:** Barriere gegen ATH-Level; verwandt mit D.

---

## 4. Fee-Struktur (NEU gegenüber Fußball)

Alle Krypto-Märkte:
```
feeType: "crypto_fees_v2"
feeSchedule: { exponent: 1, rate: 0.07, takerOnly: true, rebateRate: 0.2 }
makerBaseFee: 1000, takerBaseFee: 1000, makerRebatesFeeShareBps: 10000
```
- Taker zahlt Fee, Maker bekommt Rebate. **Edge-Floor muss die Taker-Fee einpreisen** — sonst überschätzen wir den realen Edge. Der Fußball-Zweig hatte fee-freie Märkte; diese Annahme **nicht** übernehmen.
- Für die read-only-Phase: Fee-Feld je Markt mitloggen, damit Netto-Edge = Brutto-Edge − Fee sauber getrackt wird.

---

## 5. Feld-Mapping für den Fetcher

Pro Markt-Objekt relevante Felder:

| Feld | Nutzung |
|---|---|
| `slug`, `conditionId`, `questionID` | Stabile IDs / Immutability der geposteten Signale |
| `question`, `groupItemTitle`, `groupItemThreshold` | Strike/Struktur (z. B. „↑ 6,000", „70,000") |
| `outcomes`, `outcomePrices` | Poly-Marktpreis (Anzeige-Signal) |
| `bestBid`, `bestAsk`, `spread` | Trade-Edge-Fläche (echte handelbare Preise) |
| `clobTokenIds` | Order-Book-Tiefe über CLOB |
| `liquidityNum`, `volume24hr`, `competitive` | Liquiditäts-/Qualitäts-Gates |
| `endDate`, `startDate`, `eventStartTime` | Laufzeit → Zeitwert für IV/Barrier-Modell |
| `resolutionSource` / description | **Referenz-Matching** (Chainlink vs. Binance) |
| `feeSchedule`, `feeType` | Netto-Edge-Rechnung |
| `restricted`, `acceptingOrders` | Handelbarkeit / Geoblock-Status |
| `umaBond`, `customLiveness` | Resolution-Mechanik (UMA vs. automatisch) |
| `series[].slug`, `series[].recurrence` | Familien-Zuordnung / rollierende Zeitstruktur |

**„Zwei Flächen": Anzeige-Signal aus `outcomePrices`, Trade-Edge aus `bestBid/bestAsk` + CLOB-Tiefe — getrennt halten wie im Fußball-Repo.**

---

## 6. Allowlist / Filter-Empfehlung

1. **Einschluss:** `tag_slug=crypto-prices` (1312) ODER per Asset-Tag (235/39/818), auf BTC/ETH/SOL beschränken (später DOGE/XRP/BNB/HYPE optional).
2. **Ausschluss:** Märkte mit Tag `hide-from-new` (102169) — das sind Spezial-/Kindmärkte.
3. **Familien-Klassifikation über `series[].slug`** (nicht über den Titel raten):
   - `*-up-or-down-5m` / `-15m` / `-hourly` → Familie A/B
   - `btc-multi-strikes-weekly` (45) → Familie C
   - `*-hit-price-monthly` → Familie D
   - `*-all-time-high-by` → Familie E
4. Immer `closed=false&order=startDate&ascending=false` fetchen.

---

## 7. Fair-Value-Implikationen (Herzstück)

| Familie | Modell | Referenz | Deribit-IV-Nutzung |
|---|---|---|---|
| A (5m/15m Up/Down) | Europ. Digital am Geld | Chainlink `<asset>/usd` | Kürzeste Laufzeit-IV → Drift/Diffusion |
| B (hourly Up/Down) | Europ. Digital am Geld, 1h | Binance Spot | ~1h-IV interpoliert |
| C (daily above $X) | **Europ. Digital `P(S_T>K)`** | **Binance Spot** | IV bei passender Laufzeit + Strike → BS |
| D (monthly hit) | **One-Touch-Barriere** | Binance Spot | IV → Barrier-Formel (≠ Digital) |
| E (ATH by date) | Barriere vs. ATH | Binance Spot | IV → Barrier gegen lfd. Max |

**Zwei nicht verhandelbare Regeln, die direkt aus dem Katalog folgen:**
- **Referenz muss zur Resolution-Quelle passen.** Chainlink-aufgelöste Märkte gegen Chainlink-Preis, Binance-aufgelöste gegen Binance-Spot. Sonst messen wir Basis-Rauschen als Edge.
- **Barrieren (D/E) niemals als Digitals rechnen.** Der One-Touch-Aufschlag ist real und systematisch; ihn zu ignorieren erzeugt genau die Phantom-Kante, die wir aus dem Fußball-Projekt kennen.

**Empfohlener Startpunkt für den Fair-Value-Prototyp:** Familie C (`btc-multi-strikes-weekly`). Sauberes europäisches Digital, feste Auflösungszeit, klare Binance-Referenz, hohe Liquidität (Event ≈ 0,4 Mio. USD/24h) — die direkteste, am wenigsten fehleranfällige Poly-vs-Fair-Kante zum Kalibrieren.

---

## 8. Offene Punkte / nächste Fetches

- **Deribit-IV live prüfen:** Verfügbare Laufzeiten/Strikes für BTC/ETH; für SOL ggf. keine liquide Deribit-Optionskette → Fair-Value für SOL-Threshold evtl. nur über realisierte Vola.
- **Chainlink Data Stream** als Preisquelle für Familie A live gegenchecken (Latenz, Zugriff).
- **`bitcoin-hit-price-monthly`** Serien-ID final verifizieren (ETH=10017, SOL=10032 bestätigt; BTC per Muster erwartet, noch nicht per ID gesehen).
- **CLOB-Tiefe** je `clobTokenId` abrufen (Order-Book-Endpoint aus dem Fußball-Repo portieren).
- **Fee-Impact quantifizieren:** Ab welchem Brutto-Edge lohnt Familie C/D nach Taker-Fee?
