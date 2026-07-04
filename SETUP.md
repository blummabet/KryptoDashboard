# CryptoEdge — GitHub-Setup (read-only Dashboard live bringen)

Ziel: das Repo auf GitHub, die Seite auf GitHub Pages, der Cron läuft. **Kein Trading.**
Du pushst via GitHub Desktop; die Schritte, die nur du machen kannst, sind mit **[DU]** markiert.

---

## 1. Repo lokal vorbereiten
Der Projektordner ist bereits ein sauberes Repo-Verzeichnis:
- `.gitignore` schließt `outputs/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store` aus — der alte
  Kit-/Card-Kram in `outputs/` wandert also **nicht** mit ins Repo.
- `data/.gitkeep` hält den Historien-Ordner leer im Repo (füllt sich über den Cron).

## 2. [DU] Neues GitHub-Repo anlegen
1. Auf github.com → **New repository**.
2. Name z.B. `crypto-edge`. **Public** wählen (GitHub Pages ist bei privaten Repos nur mit
   bezahltem Plan möglich).
3. **Kein** README/.gitignore/License hinzufügen (haben wir schon lokal). → **Create repository**.

## 3. [DU] Ordner pushen (GitHub Desktop)
1. GitHub Desktop → **File → Add local repository** → den Projektordner `KryptoDashboard` wählen.
2. Meldet er „this directory is not a git repository", auf **create a repository** klicken.
3. Commit alles (Summary z.B. „initial: cryptoedge read-only") → **Publish repository** und das eben
   erstellte `crypto-edge` als Remote wählen (Häkchen „privat" **entfernen**).

## 4. [DU] GitHub Pages auf Branch /docs stellen
Repo → **Settings → Pages** → **Build and deployment** → **Source: „Deploy from a branch"** →
**Branch: `main`**, **Folder: `/docs`** → **Save**.
(Wir nutzen bewusst NICHT „GitHub Actions" — die `deploy-pages`-Action scheitert beim Cron-Andrang
mit „Deployment failed, try again later". Branch-Pages serviert `docs/` stabil, ohne Deploy-Action.)

## 5. [DU] Workflow-Rechte freigeben (WICHTIG)
Damit der Cron die Edge-Historie zurück-committen darf:
Repo → **Settings → Actions → General** → ganz unten **Workflow permissions** →
**Read and write permissions** wählen → **Save**.
(Ohne das schlägt der `data/`-Commit-Schritt fehl.)

## 6. [DU] Ersten Lauf starten
Repo → **Actions** → Workflow **„CryptoEdge Pipeline (read-only)"** → **Run workflow**.
- Die Pipeline schreibt `docs/markets.json` + `docs/clv.json` und committet sie zurück.
- GitHub Pages serviert `docs/` automatisch — **kein Deploy-Schritt mehr, der fehlschlagen kann.**
- Die Live-URL steht unter **Settings → Pages**. Das Dashboard füllt sich aus `docs/markets.json`.

## 7. Danach automatisch — kein Re-run nötig
Der Cron läuft alle 30 min: zieht die Poly-Tages-Schwellen, rechnet Fair Value (Deribit-IV),
schreibt einen Snapshot in `data/edge_history.jsonl`, zieht Auflösungen nach, aktualisiert die
CLV-Zahlen und committet `docs/`. Pages übernimmt den neuen Stand von selbst. Historie und CLV
bauen sich über die Tage auf.

---

## Worauf beim ersten Lauf achten (ehrliche Checks)
- **Referenz-Quelle:** Zeigt das Dashboard oben `Quelle: deribit ⚠️` statt `binance`, dann hat der
  US-Actions-Runner **Binance geblockt**. Genau dann brauchen wir den **self-hosted Runner** für den
  auflösungs-identischen Binance-Spot (nächster Schritt).
- **Fear & Greed:** taucht rechts im Kontext-Rail ein Wert auf? Falls nicht, im Actions-Log nach
  `⚠️ fear_greed` schauen (Struktur der API bestätigen).
- **`fairProb`/`edge` leer:** dann kam keine Deribit-IV für den Strike/Verfall durch — Log prüfen.
- **Guards:** im Actions-Log tauchen `⚠️ GUARD …`-Zeilen auf, falls unplausible Werte entstehen.

## Wenn du magst, committe nichts von Hand in `data/`
Die Historie heilt sich über den Cron. Nur Code pushen — Daten kommen automatisch.
