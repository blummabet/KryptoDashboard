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

  // ---- Bewertungs-System: Farbe/Chip sagen GUT/SCHLECHT, nicht nur +/− der Zahl ----------
  const VERD = {
    good:  ["🟢", "trägt", "var(--pos)", "rgba(47,208,138,.16)"],
    early: ["⏳", "zu früh", "var(--warn)", "rgba(240,180,60,.18)"],
    watch: ["👁", "beobachten", "var(--accent2)", "rgba(76,141,255,.16)"],
    bad:   ["🔴", "kostet", "var(--neg)", "rgba(255,93,108,.16)"],
  };
  const vchip = (state, label) => {
    const v = VERD[state] || VERD.watch;
    return `<span style="display:inline-block;padding:2px 9px;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap;background:${v[3]};color:${v[2]}">${v[0]} ${label || v[1]}</span>`;
  };
  const vcolor = (state) => state === "good" ? "pos" : state === "bad" ? "neg" : "";
  const goodBad = (v, goodIf) => (v == null ? "" : goodIf(v) ? "pos" : "neg");

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

    const kpi = (k, v, cc, sub, star) => `<div class="kpi ${star ? "star" : ""}"><div class="k">${k}</div><div class="v ${cc || ""}">${v}</div>${sub ? `<div style="margin-top:5px;font-size:11px;color:var(--muted);line-height:1.35">${sub}</div>` : ""}</div>`;
    const cells = [
      kpi("ROI (realisiert)", s.roiPct == null ? "—" : (s.roiPct > 0 ? "+" : "") + s.roiPct + "%",
        goodBad(s.roiPct, v => v > 0), "nur geschlossene Trades · <b>Ziel: > 0</b>", true),
      kpi("Offen", s.openCount ?? "0", "", "laufen noch · von max 40 · nur Info"),
      kpi("Trefferquote", s.winRate == null ? "—" : Math.round(s.winRate * 100) + "%",
        goodBad(s.winRate, v => v > 0.5), "Anteil Gewinner · <b>Ziel: > 50 %</b>"),
      kpi("Geschlossen", s.closedCount ?? "0", "", "fertig abgerechnet · nur Info"),
      kpi("Ø CLV", c.avgClvPP == null ? "—" : (c.avgClvPP > 0 ? "+" : "") + c.avgClvPP + "pp",
        goodBad(c.avgClvPP, v => v > 0), "schlägt Schlusslinie? · <b>Ziel: > 0</b> (Nordstern)"),
      kpi("Brier vs Poly", cal.betterThanPoly == null ? "—" : (cal.betterThanPoly > 0 ? "+" : "") + cal.betterThanPoly,
        goodBad(cal.betterThanPoly, v => v > 0), "besser kalibriert als der Markt? · n/a bis genug Auflösungen"),
    ];
    $("kpis").innerHTML = cells.join("");

    const hv = $("heroVerdict");
    if (hv) hv.innerHTML = vchip("early", "Papier · noch zu früh")
      + ` &nbsp;<b style="color:var(--fg)">Eine grüne Zahl heißt hier noch nicht „gut".</b> Das ist Papier-Geld, das meiste davon unrealisiert. Der ehrliche Beweis kommt erst über Wochen: <b style="color:var(--fg)">Ø CLV dauerhaft über 0</b> (wir schlagen die Schlusslinie) und <b style="color:var(--fg)">realisierter Gewinn nach Fee</b>. Bis dahin: beobachten und lernen, nicht feiern.`;
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
      let wc = "";
      if (m.whale) {
        const w = m.whale, net = w.yesNetUSD != null ? w.yesNetUSD : (w.netFlowUSD || 0);
        const col = net > 0 ? "var(--pos)" : (net < 0 ? "var(--neg)" : "var(--muted)");
        const nn = Math.abs(net) >= 1000 ? "$" + Math.round(net / 1000) + "k" : "$" + Math.round(net);
        const sig = m.whaleSignal ? " · " + (m.whaleSignal.adjPP > 0 ? "+" : "") + m.whaleSignal.adjPP + "pp" : "";
        wc = `<span class="fam" style="background:rgba(76,141,255,.16);color:var(--accent2)" title="${esc(w.evidence || "")}">🐋 ${w.uniqueWallets}w · <span style="color:${col}">${net > 0 ? "+" : ""}${nn}</span>${sig}</span>`;
      }
      return `<tr>
        <td><span class="asset"><span class="coin" style="background:${coinColors[a] || "#888"}">${a[0]}</span>${a}</span>
            <div class="mkt-sub">${famChip(m.family)}${esc(m.market)}${wc}</div></td>
        <td class="r num">${pct(m.polyPrice)}</td><td class="r num">${pct(m.fairProb)}</td>
        <td class="r num">${m.ivPct != null ? m.ivPct.toFixed(0) + "%" : "—"}</td>
        <td>${sparkline(trends[m.conditionId])}</td>
        <td class="r"><div class="edge-cell">${edgeBar(e)}<span><span class="edgeval ${cls(e)}">${eTxt}</span>${gross}</span></div></td>
        <td class="r num">${m.edgePerDay != null ? (m.edgePerDay > 0 ? "+" : "") + m.edgePerDay.toFixed(2) + "pp" : "—"}${m.daysLeft != null ? `<div class="grosslbl">${m.daysLeft}d</div>` : ""}</td>
        <td class="r num">${usd(m.liquidityUSD)}</td></tr>`;
    }).join("") : '<tr><td colspan="8" class="empty">markets.json noch nicht vorhanden.</td></tr>';

    const wl = (data.markets || []).filter(m => m.whale);
    const wsig = wl.filter(m => m.whaleSignal).length;
    if ($("whaleHint")) $("whaleHint").innerHTML = wl.length
      ? `· 🐋 ${wl.length} mit Whale-Daten, ${wsig} mit Cluster-Signal`
      : "· 🐋 Whale-Daten ab 1. Lauf mit API-Key";

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
    const mo = (mk && mk.markout) || {};
    const moTxt = mo.avgMarkoutPP == null ? "—" : (mo.avgMarkoutPP > 0 ? "+" : "") + mo.avgMarkoutPP + "pp";
    const moCol = mo.avgMarkoutPP == null ? "var(--muted)" : (mo.avgMarkoutPP >= 0 ? "var(--pos)" : "var(--neg)");
    $("makerHint").innerHTML = ((mk && mk.count) || 0) + " Märkte · " + ((mk && mk.rewardEligible) || 0)
      + " reward-berechtigt · <b style='color:var(--accent)'>~" + day + "/Tag</b> Rewards · kumuliert <b style='color:var(--accent)'>" + cum + "</b>";

    // Markout-Vergleich: roh → gehedged → selektiv+gehedged. Zeigt, ob Adverse Selection hedgebar ist.
    const ppTxt = (v) => v == null ? "—" : (v > 0 ? "+" : "") + v + "pp";
    const ppCol = (v) => v == null ? "var(--muted)" : (v >= 0 ? "var(--pos)" : "var(--neg)");
    const nSel = mk && mk.board ? mk.board.filter(x => x.makerSelect).length : 0;
    const cell = (label, v, hint) => `<div style="flex:1;min-width:150px">
      <div class="lbl">${label}</div>
      <div class="v" style="color:${ppCol(v)}">${ppTxt(v)}</div>
      <div style="font-size:11px;color:var(--muted);margin-top:2px">${hint}</div></div>`;
    const verdict = (mo.avgSelectiveHedgedPP != null && mo.avgSelectiveHedgedPP >= 0)
      ? vchip("good", "hedgebar → Making trägt")
      : (mo.avgHedgedPP != null && mo.avgHedgedPP > (mo.avgMarkoutPP == null ? -99 : mo.avgMarkoutPP)
        ? vchip("early", "Hedge hilft, noch nicht positiv") : vchip("watch", "sammelt Fills"));
    $("makerMarkout").innerHTML = `
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;margin:2px 0 8px">
        ${cell("Roh", mo.avgMarkoutPP, (mo.fills || 0) + " Fills · ungehedged")}
        <div style="font-size:20px;color:var(--muted);align-self:center">→</div>
        ${cell("Delta-gehedged", mo.avgHedgedPP, "BTC-Spot-Teil rausgerechnet")}
        <div style="font-size:20px;color:var(--muted);align-self:center">→</div>
        ${cell("Selektiv + gehedged", mo.avgSelectiveHedgedPP, (mo.selFills || 0) + " Fills · " + nSel + " Märkte tauglich")}
      </div>
      <div>${verdict}</div>`;

    $("makerRows").innerHTML = b.length ? b.map(x => `<tr>
      <td><div class="mkt-sub">${famChip(x.family)}${x.makerSelect ? '<span class="fam" style="background:rgba(47,208,138,.16);color:var(--pos)" title="maker-tauglich: genug Liq, nicht am Rand, nicht kurz vor Auflösung">tauglich</span>' : ""}${x.isNew ? '<span class="fam" style="background:rgba(76,141,255,.16);color:var(--accent2)">NEU</span>' : ""}${esc(x.market)}</div></td>
      <td class="r num">${pct(x.fair)}</td>
      <td class="r num">${x.bid != null ? cents(x.bid) + "/" + cents(x.ask) : "—"}</td>
      <td class="r num">${cents(x.quoteBid)}/${cents(x.quoteAsk)}</td>
      <td class="r pnl pos">+${x.edgeIfFilledPP.toFixed(1)}pp</td>
      <td class="r num">${x.rewardEligible ? "$" + (x.estRewardDay || 0).toFixed(3) + "/T" : "<span class='mkt-sub'>—</span>"}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">Kein Maker-Board — noch keine Märkte mit Fair.</td></tr>';
  }

  // ---- Analyse: CLV-vs-P&L-Lücke + BTC-Klumpenrisiko -------------------------------------
  function renderAnalysis(an) {
    const a = (an && an.attribution) || {}, e = (an && an.btcExposure) || {};
    if (a.nClosed) {
      const feeVerd = a.feeEatsEdge ? vchip("bad", "Fee frisst den Edge") : vchip("good", "Edge > Fee");
      $("attribBody").innerHTML = `
        <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:baseline;margin:2px 0 12px">
          <div><div class="lbl">Brutto (vor Fee)</div><div class="v pos">${money(a.grossBeforeFees)}</div></div>
          <div style="font-size:20px;color:var(--muted)">−</div>
          <div><div class="lbl">Taker-Fees</div><div class="v neg">−$${Math.abs(a.feesTotal).toFixed(2)}</div></div>
          <div style="font-size:20px;color:var(--muted)">=</div>
          <div><div class="lbl">Netto realisiert</div><div class="v ${cls(a.realizedTotal)}">${money(a.realizedTotal)}</div></div>
        </div>
        <div style="margin-bottom:8px">${feeVerd} &nbsp;<b>Ø Fee ${a.avgFeePP}pp</b> vs <b>Ø Einstiegs-Edge ${a.avgEntryEdgePP}pp</b> — die Taker-Fee ist größer als die Kante.</div>
        <div class="ctx-note">Trefferquote ${Math.round(a.winRate * 100)} % · Payoff ${a.payoffRatio} (Gewinner ≈ Verlierer gleich groß) · die 5 schlimmsten Trades = ${money(a.worstFiveSum)} (${Math.round(a.tailLossShare * 100)} % aller Verluste). <b>Vor Fee leicht positiv (${money(a.grossBeforeFees)}), nach Taker-Fee negativ</b> — genau die These: Taker-Konvergenz ist nach Fee tot, der tragfähige Weg ist Maker (zahlt keine Fee).</div>`;
    }
    if (e.n) {
      const long = e.longStakeUSD || 0, short = e.shortStakeUSD || 0, tot = (long + short) || 1;
      const lp = Math.round(long / tot * 100), sp = 100 - lp;
      const verd = e.concentrated ? vchip("bad", "einseitige BTC-Wette") : vchip("good", "ausgewogen");
      const fallsSteigt = e.netPct < 0 ? "FÄLLT" : "STEIGT";
      $("exposureBody").innerHTML = `
        <div style="font-size:26px;font-weight:800;margin:2px 0 8px">Netto-BTC ${e.netPct > 0 ? "+" : ""}${e.netPct} % <span style="font-size:14px;color:var(--muted)">${(e.direction || "").split(" ")[0]}</span></div>
        <div style="display:flex;height:14px;border-radius:7px;overflow:hidden;margin-bottom:8px" title="grün = bullish, rot = bearish">
          <div style="width:${lp}%;background:var(--pos)"></div><div style="width:${sp}%;background:var(--neg)"></div></div>
        <div style="margin-bottom:8px">${verd} &nbsp;${e.nLong} bullish / ${e.nShort} bearish von ${e.n} offenen Positionen</div>
        <div class="ctx-note">Fast alle offenen Positionen ziehen in dieselbe Richtung: das Buch gewinnt, wenn BTC <b>${fallsSteigt}</b>. Das ist <b>keine Fehlbepreisungs-Ernte, sondern eine gerichtete BTC-Wette</b> — daher die großen Tagesschwankungen (z.B. −$742). Sauberes Edge-Ernten wäre marktneutral (long ≈ short).</div>`;
    }
  }

  // ---- Verlauf Tag für Tag ----------------------------------------------------------------
  function renderTrend(sb) {
    const days = (sb && sb.days) || [];
    $("trendDay").textContent = "Tag " + ((sb && sb.dayNo) || days.length || 0)
      + (sb && sb.startDate ? " · seit " + sb.startDate : "");
    const money = (v) => v == null ? "—" : (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(0);
    const rows = days.slice(-14).reverse();   // neueste oben, max. 14 Tage
    $("trendRows").innerHTML = rows.length ? rows.map(d => `<tr>
      <td class="mkt-sub">${d.date}</td>
      <td class="r pnl ${cls(d.convergePnl)}">${money(d.convergePnl)}</td>
      <td class="r pnl ${cls(d.arbLocked)}">${money(d.arbLocked)}</td>
      <td class="r num">${d.makerCumReward != null ? "$" + d.makerCumReward.toFixed(2) : "—"}</td>
      <td class="r pnl ${cls(d.clvPP)}">${d.clvPP != null ? (d.clvPP > 0 ? "+" : "") + d.clvPP + "pp" : "—"}</td>
      <td class="r num">${d.basketTradable != null ? d.basketTradable : "—"}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">Noch kein Verlauf — ab dem ersten Cron-Lauf kommt täglich eine Zeile dazu.</td></tr>';
  }

  // ---- Multi-Outcome Basket-Arb (alle Kategorien) ----------------------------------------
  function renderBaskets(b) {
    const f = (b && b.findings) || [];
    $("basketHint").innerHTML = ((b && b.scanned) || 0) + " Kandidaten gescannt · "
      + ((b && b.count) || 0) + " Σ≠100 %-Funde · <b>" + ((b && b.tradableCount) || 0) + " robust handelbar</b>";
    $("basketRows").innerHTML = f.length ? f.map(x => {
      const sideTxt = x.side === "sell" ? "Verkauf-Korb" : "Kauf-Korb";
      const sideCls = x.side === "sell" ? "side-YES" : "side-NO";
      const cav = x.exhaustiveNeeded ? " ⚠️" : "";
      return `<tr>
        <td><div class="mkt-sub">${esc(x.event)}</div></td>
        <td class="r num">${x.n}</td>
        <td class="r num">${pct(x.sumProb)}</td>
        <td class="r"><span class="side ${sideCls}">${sideTxt}${cav}</span></td>
        <td class="r pnl ${x.netPP > 0 ? "pos" : ""}">${x.netPP.toFixed(1)}pp</td>
        <td class="r">${x.tradable ? '<span class="side side-YES">JA</span>' : '<span class="mkt-sub">—</span>'}</td></tr>`;
    }).join("")
      : '<tr><td colspan="6" class="empty">Aktuell keine Σ≠100 %-Körbe — die liquiden Multi-Outcome-Märkte sind fair bepreist (Overround). Kante taucht in dünnen/frischen Märkten auf.</td></tr>';
  }

  // ---- Einnahmen-Übersicht (alle Varianten auf einen Blick) ------------------------------
  function renderIncome(paper, arb, maker, clv, baskets) {
    const ps = (paper && paper.summary) || {}, as = (arb && arb.paper && arb.paper.summary) || {};
    const ms = (maker && maker.sim) || {}, mo = (maker && maker.markout) || {};
    const mkNet = mo.avgMarkoutPP;
    const rows = [
      { name: "Konvergenz (Taker)", val: money(ps.totalPnl), state: "early",
        note: "Poly gegen unsere Deribit-Fair handeln. Grün täuscht — das meiste ist unrealisiert. Echter Beweis: Ø CLV > 0 nach Fee über Wochen." },
      { name: "Konsistenz-Arb", val: money(as.totalPnl), state: (as.openCount || 0) > 0 ? "good" : "watch",
        note: "Polys eigene Preisleiter widerspricht sich → risikoarm. Sauberste Kante, aber selten; Ausführen braucht den Runner. (" + (as.openCount || 0) + " offen)" },
      { name: "Maker-Rewards", val: ms.estRewardDayTotal != null ? "~$" + ms.estRewardDayTotal.toFixed(2) + "/Tag" : "—", state: "watch",
        note: "Geschätzte Belohnung fürs Quoten (Poly zahlt Maker). Nur Schätzung — echt erst mit Runner. Richtung stimmt, Höhe unsicher." },
      { name: "Maker netto (Markout)",
        val: (mo.avgSelectiveHedgedPP != null ? mo.avgSelectiveHedgedPP : (mo.avgHedgedPP != null ? mo.avgHedgedPP : mkNet)) != null
          ? ((v => (v > 0 ? "+" : "") + v + "pp")(mo.avgSelectiveHedgedPP != null ? mo.avgSelectiveHedgedPP : (mo.avgHedgedPP != null ? mo.avgHedgedPP : mkNet))) : "—",
        state: (mo.avgSelectiveHedgedPP != null ? mo.avgSelectiveHedgedPP : mo.avgHedgedPP) == null
          ? (mkNet == null ? "watch" : (mkNet >= 0 ? "good" : "bad"))
          : ((mo.avgSelectiveHedgedPP != null ? mo.avgSelectiveHedgedPP : mo.avgHedgedPP) >= 0 ? "good" : "bad"),
        note: "Nach Delta-Hedge + Selektivität (roh " + (mkNet != null ? mkNet + "pp" : "—") + "). Positiv = Adverse Selection ist hedgebar → Making trägt. Details im Maker-Tab." },
      { name: "Neu-Markt-Lag", val: money(ps.newMarketPnl), state: "early",
        note: "Frische Märkte starten träge bei ~50¢. Sieht ertragreich aus, ist aber evtl. nur Illiquidität — erst über Auflösungen beweisen. (" + (ps.newMarketCount || 0) + " Trades)" },
      { name: "Multi-Outcome Basket-Arb",
        val: (baskets && baskets.tradableCount) ? baskets.tradableCount + " handelbar" : ((baskets && baskets.count) ? baskets.count + " Funde" : "—"),
        state: (baskets && baskets.tradableCount) ? "good" : "watch",
        note: "Mehrere exklusive Antworten (WM, Wahlen): Summe aller Ja ≠ 100 % = risikofrei. Funde = erkannt (meist zu klein oder wegarbitriert); handelbar = echt lohnend." },
    ];
    $("incomeRows").innerHTML = rows.map(r => `<tr>
      <td><b>${r.name}</b></td>
      <td class="r pnl ${vcolor(r.state)}">${r.val}</td>
      <td>${vchip(r.state)}</td>
      <td class="mkt-sub">${r.note}</td></tr>`).join("");
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
      tile("maker", "Maker · Markout", ((mk && mk.markout && mk.markout.avgMarkoutPP) == null) ? "—" : (mk.markout.avgMarkoutPP > 0 ? "+" : "") + mk.markout.avgMarkoutPP + "pp", cls(mk && mk.markout && mk.markout.avgMarkoutPP), ((mk && mk.rewardEligible) ?? 0) + " berechtigt · Reward $" + (((mk && mk.sim && mk.sim.cumRewardEst)) || 0)),
      tile("radar", "Neu-Markt-Lag", nm == null ? money(0) : money(nm), cls(nm), (s.newMarketCount ?? 0) + " Trades · frisch"),
    ].join("");
    document.querySelectorAll(".stile").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.goto)));
  }

  // ---- Tabs -------------------------------------------------------------------------------
  const VIEWS = ["portfolio", "radar", "arb", "baskets", "maker"];
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
  Promise.allSettled([j("paper.json"), j("clv.json"), j("markets.json"), j("arb.json"), j("maker.json"), j("baskets.json"), j("scoreboard.json"), j("analysis.json")])
    .then(([pp, cl, mk, ar, ma, bk, sb, an]) => {
      const paper = pp.status === "fulfilled" ? pp.value : {};
      const clv = cl.status === "fulfilled" ? cl.value : {};
      const markets = mk.status === "fulfilled" ? mk.value : {};
      const arb = ar.status === "fulfilled" ? ar.value : {};
      const maker = ma.status === "fulfilled" ? ma.value : {};
      const baskets = bk.status === "fulfilled" ? bk.value : {};
      const scoreboard = sb.status === "fulfilled" ? sb.value : {};
      const analysis = an.status === "fulfilled" ? an.value : {};
      renderHero(paper, clv);
      renderIncome(paper, arb, maker, clv, baskets);
      renderTrend(scoreboard);
      renderAnalysis(analysis);
      renderStrat(paper, arb, maker, markets);
      renderPortfolio(paper);
      renderRadar(markets, clv.trends || {});
      if (markets.generatedAt) $("updated").textContent = "Stand: " + markets.generatedAt;
      renderArb(arb);
      renderBaskets(baskets);
      renderMaker(maker);
    });
})();
