// app.js — CryptoEdge Paper-Trading Dashboard (read-only / dry-run). Lädt markets.json, clv.json
// und paper.json (von der Python-Pipeline erzeugt) und rendert Portfolio + Edge-Radar. Kein Trading.
(function () {
  "use strict";
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const pct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  const cents = (x) => (x == null ? "—" : (x * 100).toFixed(0) + "¢");
  const usd = (x) => (x == null ? "—" : "$" + Math.round(x).toLocaleString("de-DE"));
  const money = (x) => (x == null ? "—" : (x >= 0 ? "+$" : "−$") + Math.abs(x).toFixed(2));
  const cls = (x) => (x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");
  const coinColors = { BTC: "#f7931a", ETH: "#627eea", SOL: "#14f195" };

  // ---- SVG helpers (Radar) ----------------------------------------------------------------
  function sparkline(vals) {
    if (!vals || vals.length < 2) return '<span class="mkt-sub">—</span>';
    const w = 70, h = 20, p = 2, lo = Math.min(...vals), hi = Math.max(...vals), sp = (hi - lo) || 1;
    const pts = vals.map((v, i) => (p + (i / (vals.length - 1)) * (w - 2 * p)).toFixed(1) + "," + (p + (1 - (v - lo) / sp) * (h - 2 * p)).toFixed(1)).join(" ");
    const last = vals[vals.length - 1], col = last > 0 ? "var(--pos)" : last < 0 ? "var(--neg)" : "var(--dim)";
    const zy = p + (1 - (0 - lo) / sp) * (h - 2 * p);
    const zero = (0 >= lo && 0 <= hi) ? `<line x1="0" y1="${zy.toFixed(1)}" x2="${w}" y2="${zy.toFixed(1)}" stroke="rgba(255,255,255,.12)" stroke-dasharray="2 2"/>` : "";
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${zero}<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts}"/></svg>`;
  }
  function edgeBar(pp) {
    if (pp == null) return "";
    const f = Math.min(Math.abs(pp), 12) / 12, W = 35, col = pp > 0 ? "var(--pos)" : "var(--neg)";
    const st = pp > 0 ? `left:50%;width:${(f * W).toFixed(0)}px` : `right:50%;width:${(f * W).toFixed(0)}px`;
    return `<span class="edgebar"><i style="${st};background:${col}"></i></span>`;
  }
  function fgGauge(v) {
    if (v == null) return '<div class="mkt-sub">Fear &amp; Greed n/a</div>';
    const W = 190, H = 104, cx = W / 2, cy = 94, r = 78, a0 = Math.PI, a = a0 + (0 - a0) * (v / 100);
    const pol = (ang) => [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
    const s = pol(a0), e = pol(0), n = pol(a);
    const col = v < 25 ? "var(--neg)" : v < 45 ? "var(--warn)" : v < 55 ? "#c9d24a" : v < 75 ? "#7fd04a" : "var(--pos)";
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
      + `<path d="M${s[0].toFixed(1)} ${s[1].toFixed(1)} A${r} ${r} 0 0 1 ${e[0].toFixed(1)} ${e[1].toFixed(1)}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="10" stroke-linecap="round"/>`
      + `<path d="M${s[0].toFixed(1)} ${s[1].toFixed(1)} A${r} ${r} 0 0 1 ${n[0].toFixed(1)} ${n[1].toFixed(1)}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"/>`
      + `<circle cx="${n[0].toFixed(1)}" cy="${n[1].toFixed(1)}" r="5" fill="${col}"/></svg>`;
  }
  const famChip = (f) => { const l = { above: "Schwelle", touch: "Touch" }[f]; return l ? `<span class="fam fam-${f}">${l}</span>` : ""; };

  // ---- Hero + KPIs ------------------------------------------------------------------------
  function renderHero(paper, clv) {
    const s = (paper && paper.summary) || {}, c = (clv && clv.summary) || {}, cal = (clv && clv.calibration) || {};
    const t = $("totalPnl");
    t.textContent = s.totalPnl == null ? "—" : money(s.totalPnl);
    t.className = "big " + cls(s.totalPnl);
    $("realPnl").innerHTML = `<span class="${cls(s.realizedPnl)}">${money(s.realizedPnl)}</span>`;
    $("unrealPnl").innerHTML = `<span class="${cls(s.unrealizedPnl)}">${money(s.unrealizedPnl)}</span>`;
    if (s.mode) $("modechip").textContent = s.mode.replace("PAPER / DRY-RUN — ", "") + " · $" + (s.stakeUSD || 100) + "/Trade";

    const kpi = (k, v, cc, star) => `<div class="kpi ${star ? "star" : ""}"><div class="k">${k}</div><div class="v ${cc || ""}">${v}</div></div>`;
    const cells = [
      kpi("ROI (realisiert)", s.roiPct == null ? "—" : (s.roiPct > 0 ? "+" : "") + s.roiPct + "%", cls(s.roiPct), true),
      kpi("Offen", s.openCount ?? "0", ""),
      kpi("Trefferquote", s.winRate == null ? "—" : Math.round(s.winRate * 100) + "%", ""),
      kpi("Geschlossen", s.closedCount ?? "0", ""),
      kpi("Ø CLV", c.avgClvPP == null ? "—" : (c.avgClvPP > 0 ? "+" : "") + c.avgClvPP + "pp", cls(c.avgClvPP)),
      kpi("Brier vs Poly", cal.betterThanPoly == null ? "—" : (cal.betterThanPoly > 0 ? "+" : "") + cal.betterThanPoly, cls(cal.betterThanPoly)),
    ];
    $("kpis").innerHTML = cells.join("");
  }

  // ---- Portfolio --------------------------------------------------------------------------
  function renderPortfolio(paper) {
    const p = paper || {};
    const open = p.open || [], closed = p.closed || [], act = p.activity || [];
    $("openHint").textContent = open.length + " offen";
    $("closedHint").textContent = closed.length + " geschlossen";

    $("openRows").innerHTML = open.length ? open.map(o => {
      const raw = o.curEdgePP == null ? o.entryEdgePP : o.curEdgePP;   // remaining IN unsere Richtung
      const rem = raw == null ? null : (o.side === "YES" ? raw : -raw);
      const remTxt = rem == null ? "—" : (rem > 0 ? "+" : "") + rem.toFixed(1) + "pp";
      return `<tr>
        <td><div class="mkt-sub">${famChip(o.family)}${esc(o.market)}</div></td>
        <td><span class="side side-${o.side}">${o.side}</span></td>
        <td class="r num">${cents(o.entryPoly)}</td>
        <td class="r num">${cents(o.markPoly)}</td>
        <td class="r num">${remTxt}</td>
        <td class="r num">${o.ageH == null ? "—" : o.ageH < 48 ? o.ageH + "h" : Math.round(o.ageH / 24) + "d"}</td>
        <td class="r pnl ${cls(o.unrealPnl)}">${money(o.unrealPnl)}</td></tr>`;
    }).join("") : '<tr><td colspan="7" class="empty">Noch keine offenen Positionen — die Engine öffnet ab ' + (p.summary ? p.summary.edgeFloorPP : 2.5) + 'pp Netto-Edge.</td></tr>';

    $("closedRows").innerHTML = closed.length ? closed.map(c => `<tr>
        <td><div class="mkt-sub">${famChip(c.family)}${esc(c.market)}</div></td>
        <td><span class="side side-${c.side}">${c.side}</span></td>
        <td class="r num">${cents(c.entryPoly)}</td>
        <td class="r num">${c.exitMark === 0 || c.exitMark === 1 ? (c.exitMark === 1 ? "Ja ✓" : "Nein ✗") : cents(c.exitMark)}</td>
        <td><span class="rsn rsn-${c.exitReason}">${({ converged: "konvergiert", thesis_break: "these gebrochen", resolved_win: "aufgelöst ✓", resolved_loss: "aufgelöst ✗" })[c.exitReason] || c.exitReason}</span></td>
        <td class="r pnl ${cls(c.realizedPnl)}">${money(c.realizedPnl)}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">Noch keine geschlossenen Positionen.</td></tr>';

    $("feed").innerHTML = act.length ? act.map(a => {
      let ico, icls, txt;
      if (a.type === "open") { ico = "▲"; icls = "fi-open"; txt = `<b>${a.side}</b> eröffnet · ${esc(a.market)} @ ${cents(a.entry)} · ${a.edge > 0 ? "+" : ""}${(a.edge || 0).toFixed(1)}pp`; }
      else if (a.type === "settle") { ico = "⚑"; icls = "fi-settle"; txt = `aufgelöst · ${esc(a.market)}`; }
      else { ico = "✓"; icls = "fi-close"; txt = `${a.reason === "thesis_break" ? "these gebrochen" : "konvergiert"} · ${esc(a.market)}`; }
      const pnl = a.pnl == null ? "" : `<span class="fpnl ${cls(a.pnl)}">${money(a.pnl)}</span>`;
      return `<div class="fitem"><span class="fico ${icls}">${ico}</span><span class="ftxt">${txt}</span>${pnl}</div>`;
    }).join("") : '<div class="empty">Noch keine Aktivität.</div>';
  }

  // ---- Radar ------------------------------------------------------------------------------
  function renderRadar(data, trends) {
    const rows = (data.markets || []).slice().sort((a, b) => (a.edgePP == null) - (b.edgePP == null) || (b.edgePP || 0) - (a.edgePP || 0));
    $("radarRows").innerHTML = rows.length ? rows.map(m => {
      const a = m.asset || "?", e = m.edgePP;
      const eTxt = e == null ? "—" : (e > 0 ? "+" : "") + e.toFixed(1) + "pp";
      const gross = (m.edgeGrossPP != null && e != null) ? `<div class="grosslbl">brutto ${(m.edgeGrossPP > 0 ? "+" : "") + m.edgeGrossPP.toFixed(1)}</div>` : "";
      return `<tr>
        <td><span class="asset"><span class="coin" style="background:${coinColors[a] || "#888"}">${a[0]}</span>${a}</span>
            <div class="mkt-sub">${famChip(m.family)}${esc(m.market)}</div></td>
        <td class="r num">${pct(m.polyPrice)}</td><td class="r num">${pct(m.fairProb)}</td>
        <td class="r num">${m.ivPct != null ? m.ivPct.toFixed(0) + "%" : "—"}</td>
        <td>${sparkline(trends[m.conditionId])}</td>
        <td class="r"><div class="edge-cell">${edgeBar(e)}<span><span class="edgeval ${cls(e)}">${eTxt}</span>${gross}</span></div></td>
        <td class="r num">${usd(m.liquidityUSD)}</td></tr>`;
    }).join("") : '<tr><td colspan="7" class="empty">markets.json noch nicht vorhanden.</td></tr>';

    const fg = (data.context || {}).fearGreed;
    $("gauge").innerHTML = fg ? fgGauge(fg.value) + `<div class="gauge-val" style="color:${fg.value != null && fg.value < 45 ? "var(--warn)" : "var(--pos)"}">${fg.value ?? "—"}</div><div class="gauge-cls">Fear &amp; Greed · ${esc(fg.classification || "—")}</div>` : '<div class="mkt-sub">Fear &amp; Greed n/a</div>';
    $("csignals").innerHTML = (data.contextSignals || []).map(s => `<div class="csig"><div><div class="nm">${esc(s.name)}</div><div class="ev">${esc(s.evidence || s.family)}</div></div><span class="adj ${cls(s.adjPP)}">${s.silent ? "—" : (s.adjPP > 0 ? "+" : "") + s.adjPP + "pp"}</span></div>`).join("");
    const ref = data.reference || {};
    $("refline").innerHTML = `Spot <b class="num">${ref.spot ? "$" + ref.spot.toLocaleString("de-DE") : "—"}</b> · Quelle <b>${esc(ref.spotSource || "—")}</b> · ATM-IV <b class="num">${ref.iv != null ? (ref.iv * 100).toFixed(0) + "%" : "—"}</b>`;
  }

  // ---- Konsistenz-Arb (Paper-Buch + gefundene Widersprüche) -------------------------------
  function renderArb(a) {
    const f = (a && a.findings) || [];
    const pb = (a && a.paper) || {}, s = pb.summary || {}, op = pb.open || [];
    const kpi = (k, v, cc) => `<div class="kpi"><div class="k">${k}</div><div class="v ${cc || ""}">${v}</div></div>`;
    $("arbKpis").innerHTML = [
      kpi("Arb P&L", s.totalPnl == null ? "—" : money(s.totalPnl), cls(s.totalPnl)),
      kpi("gesperrt (offen)", s.lockedOpen == null ? "—" : money(s.lockedOpen), cls(s.lockedOpen)),
      kpi("realisiert", s.realizedPnl == null ? "—" : money(s.realizedPnl), cls(s.realizedPnl)),
      kpi("Offen / Settled", (s.openCount ?? 0) + " / " + (s.closedCount ?? 0), ""),
    ].join("");

    $("arbOpenHint").textContent = op.length + " offen";
    $("arbOpenRows").innerHTML = op.length ? op.map(o => `<tr>
      <td><div class="mkt-sub">${esc(o.label)}</div></td>
      <td class="r pnl pos">${o.gapPP.toFixed(1)}pp</td>
      <td class="r num">${cents(o.cost)}</td>
      <td class="r pnl ${cls(o.lockedMin)}">${money(o.lockedMin)}</td></tr>`).join("")
      : '<tr><td colspan="4" class="empty">Noch keine offenen Arbitragen — sobald ein Gap ≥ ~7pp auftaucht, wird gehandelt.</td></tr>';

    $("arbHint").textContent = ((a && a.count) || 0) + " Widersprüche · " + ((a && a.tradableCount) || 0) + " handelbar";
    $("arbRows").innerHTML = f.length ? f.map(x => `<tr>
      <td><div class="mkt-sub">${esc(x.note)}</div></td>
      <td class="r num">${pct(x.lowP)}</td><td class="r num">${pct(x.highP)}</td>
      <td class="r pnl ${x.tradable ? "pos" : ""}">${x.gapPP.toFixed(1)}pp</td>
      <td class="r">${x.tradable ? '<span class="side side-YES">JA</span>' : '<span class="mkt-sub">—</span>'}</td></tr>`).join("")
      : '<tr><td colspan="5" class="empty">Aktuell keine Widersprüche — Polys Strike-Leiter ist konsistent.</td></tr>';
  }

  // ---- Maker-Board ------------------------------------------------------------------------
  function renderMaker(mk) {
    const b = (mk && mk.board) || [], sim = (mk && mk.sim) || {};
    const cum = sim.cumRewardEst == null ? "—" : "$" + sim.cumRewardEst.toFixed(2);
    const day = sim.estRewardDayTotal == null ? "—" : "$" + sim.estRewardDayTotal.toFixed(2);
    $("makerHint").innerHTML = ((mk && mk.count) || 0) + " Märkte · " + ((mk && mk.rewardEligible) || 0)
      + " reward-berechtigt · <b style='color:var(--accent)'>~" + day + "/Tag</b> geschätzt · kumuliert <b style='color:var(--accent)'>" + cum + "</b>";
    $("makerRows").innerHTML = b.length ? b.map(x => `<tr>
      <td><div class="mkt-sub">${famChip(x.family)}${x.isNew ? '<span class="fam" style="background:rgba(76,141,255,.16);color:var(--accent2)">NEU</span>' : ""}${esc(x.market)}</div></td>
      <td class="r num">${pct(x.fair)}</td>
      <td class="r num">${x.bid != null ? cents(x.bid) + "/" + cents(x.ask) : "—"}</td>
      <td class="r num">${cents(x.quoteBid)}/${cents(x.quoteAsk)}</td>
      <td class="r pnl pos">+${x.edgeIfFilledPP.toFixed(1)}pp</td>
      <td class="r num">${x.rewardEligible ? "$" + (x.estRewardDay || 0).toFixed(3) + "/T" : "<span class='mkt-sub'>—</span>"}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">Kein Maker-Board — noch keine Märkte mit Fair.</td></tr>';
  }

  // ---- Strategie-Übersicht (oben, je Strategie eine Kachel) -------------------------------
  function renderStrat(paper, arb, mk, markets) {
    const s = (paper && paper.summary) || {};
    const newCount = ((markets && markets.markets) || []).filter(m => m.isNew).length;
    const tile = (goto, title, val, vc, sub) =>
      `<div class="stile" data-goto="${goto}"><div class="st">${title}</div><div class="sv ${vc || ""}">${val}</div><div class="ss">${sub}</div></div>`;
    const ap = (arb && arb.paper && arb.paper.summary) || {};
    const nm = s.newMarketPnl;
    $("strat").innerHTML = [
      tile("portfolio", "Paper-Trading", s.totalPnl == null ? "—" : money(s.totalPnl), cls(s.totalPnl), (s.openCount ?? 0) + " offen · Konvergenz"),
      tile("arb", "Konsistenz-Arb", ap.totalPnl == null ? "—" : money(ap.totalPnl), cls(ap.totalPnl), (ap.openCount ?? 0) + " offen · gesperrt"),
      tile("maker", "Maker-Board (Sim)", ((mk && mk.sim && mk.sim.cumRewardEst) == null) ? "—" : money(mk.sim.cumRewardEst), "acc", ((mk && mk.rewardEligible) ?? 0) + " berechtigt · Rewards gesch."),
      tile("radar", "Neu-Markt-Lag", nm == null ? money(0) : money(nm), cls(nm), (s.newMarketCount ?? 0) + " Trades · frisch"),
    ].join("");
    document.querySelectorAll(".stile").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.goto)));
  }

  // ---- Tabs -------------------------------------------------------------------------------
  const VIEWS = ["portfolio", "radar", "arb", "maker"];
  function switchTab(view) {
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x.dataset.view === view));
    VIEWS.forEach(v => $("view-" + v).classList.toggle("hidden", v !== view));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.view)));

  // ---- Load -------------------------------------------------------------------------------
  // Daten direkt aus dem Repo (raw) laden → immer frisch, unabhängig vom (oft zickigen) Pages-Deploy.
  // Fallback: gleicher Origin (docs/), falls raw mal nicht erreichbar ist.
  const RAW = "https://raw.githubusercontent.com/blummabet/KryptoDashboard/main/docs/";
  const j = (name) => {
    const bust = "?_=" + Date.now();
    return fetch(RAW + name + bust, { cache: "no-store" })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .catch(() => fetch(name + bust).then(r => r.ok ? r.json() : Promise.reject(r.status)));
  };
  Promise.allSettled([j("paper.json"), j("clv.json"), j("markets.json"), j("arb.json"), j("maker.json")])
    .then(([pp, cl, mk, ar, ma]) => {
      const paper = pp.status === "fulfilled" ? pp.value : {};
      const clv = cl.status === "fulfilled" ? cl.value : {};
      const markets = mk.status === "fulfilled" ? mk.value : {};
      const arb = ar.status === "fulfilled" ? ar.value : {};
      const maker = ma.status === "fulfilled" ? ma.value : {};
      renderHero(paper, clv);
      renderStrat(paper, arb, maker, markets);
      renderPortfolio(paper);
      renderRadar(markets, clv.trends || {});
      if (markets.generatedAt) $("updated").textContent = "Stand: " + markets.generatedAt;
      renderArb(arb);
      renderMaker(maker);
    });
})();
