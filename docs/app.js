// app.js — CryptoEdge Dashboard (read-only). Lädt markets.json + clv.json (von der Python-
// Pipeline erzeugt) und rendert die zwei Flächen: Trade-Edge-Tabelle + Kontext-Rail. Kein Trading.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  const usd = (x) => (x == null ? "—" : "$" + Math.round(x).toLocaleString("de-DE"));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const coinColors = { BTC: "#f7931a", ETH: "#627eea", SOL: "#14f195" };

  // ---- SVG-Helfer -------------------------------------------------------------------------
  function sparkline(vals) {
    if (!vals || vals.length < 2) return '<span class="mkt-sub">—</span>';
    const w = 74, h = 20, pad = 2;
    const lo = Math.min(...vals), hi = Math.max(...vals), span = (hi - lo) || 1;
    const pts = vals.map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - 2 * pad);
      const y = pad + (1 - (v - lo) / span) * (h - 2 * pad);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    const last = vals[vals.length - 1];
    const col = last > 0 ? "var(--pos)" : (last < 0 ? "var(--neg)" : "var(--dim)");
    const zeroY = pad + (1 - (0 - lo) / span) * (h - 2 * pad);
    const zero = (0 >= lo && 0 <= hi)
      ? `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${w}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,.12)" stroke-dasharray="2 2"/>` : "";
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${zero}`
      + `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts}"/></svg>`;
  }

  function edgeBar(pp) {
    if (pp == null) return "";
    const cap = 12, frac = Math.min(Math.abs(pp), cap) / cap, W = 76 / 2;
    const col = pp > 0 ? "var(--pos)" : "var(--neg)";
    const style = pp > 0 ? `left:50%;width:${(frac * W).toFixed(0)}px` : `right:50%;width:${(frac * W).toFixed(0)}px`;
    return `<span class="edgebar"><i style="${style};background:${col}"></i></span>`;
  }

  function fgGauge(v) {
    if (v == null) return '<div class="mkt-sub">Fear &amp; Greed n/a</div>';
    const W = 190, H = 108, cx = W / 2, cy = 96, r = 78;
    const a0 = Math.PI, a1 = 0, a = a0 + (a1 - a0) * (v / 100);
    const pol = (ang) => [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
    const [sx, sy] = pol(a0), [ex, ey] = pol(a1), [nx, ny] = pol(a);
    const col = v < 25 ? "var(--neg)" : v < 45 ? "var(--warn)" : v < 55 ? "#c9d24a" : v < 75 ? "#7fd04a" : "var(--pos)";
    const [px, py] = pol(a);
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
      + `<path d="M${sx.toFixed(1)} ${sy.toFixed(1)} A${r} ${r} 0 0 1 ${ex.toFixed(1)} ${ey.toFixed(1)}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="10" stroke-linecap="round"/>`
      + `<path d="M${sx.toFixed(1)} ${sy.toFixed(1)} A${r} ${r} 0 0 1 ${nx.toFixed(1)} ${ny.toFixed(1)}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"/>`
      + `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="5" fill="${col}"/></svg>`;
  }

  // ---- KPI-Leiste (Nordstern) -------------------------------------------------------------
  function kpi(k, v, cls, sub, star) {
    return `<div class="kpi ${star ? "star" : ""}"><div class="k">${k}</div>`
      + `<div class="v ${cls || ""}">${v}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }
  function renderKpis(clv) {
    const s = (clv && clv.summary) || {}, c = (clv && clv.calibration) || {};
    const cells = [];
    const clvCls = s.avgClvPP == null ? "" : (s.avgClvPP > 0 ? "pos" : "neg");
    const clvTxt = s.avgClvPP == null ? "—" : (s.avgClvPP > 0 ? "+" : "") + s.avgClvPP + "pp";
    cells.push(kpi("Ø CLV", clvTxt, clvCls, `${s.picks || 0} Picks · |edge|≥${s.edgeMinPP ?? 2}pp`, true));
    cells.push(kpi("CLV positiv", s.positiveClvShare == null ? "—" : Math.round(s.positiveClvShare * 100) + "%", "acc", "Schluss-Linie geschlagen"));
    cells.push(kpi("Getrackte Märkte", s.trackedMarkets || 0, "", "read-only Historie"));
    if (c.resolvedPicks) {
      const pnlCls = c.avgRealizedPnlPP == null ? "" : (c.avgRealizedPnlPP > 0 ? "pos" : "neg");
      cells.push(kpi("Trefferquote", c.hitRate != null ? Math.round(c.hitRate * 100) + "%" : "—", "", `${c.resolvedPicks} aufgelöste Picks`));
      cells.push(kpi("Ø PnL brutto", (c.avgRealizedPnlPP > 0 ? "+" : "") + (c.avgRealizedPnlPP ?? "—") + "pp", pnlCls, "vor Fee"));
      cells.push(kpi("Brier vs Poly", (c.betterThanPoly > 0 ? "+" : "") + (c.betterThanPoly ?? "—"), c.betterThanPoly > 0 ? "pos" : "neg", ">0 = wir besser kalibriert"));
    } else {
      cells.push(kpi("Kalibrierung", "wartet", "", "füllt sich bei Auflösung"));
    }
    $("kpis").innerHTML = cells.join("");
  }

  // ---- Trade-Edge-Tabelle -----------------------------------------------------------------
  function renderMarkets(data, trends) {
    const rows = (data.markets || []).slice()
      .sort((a, b) => (a.edgePP == null) - (b.edgePP == null) || (b.edgePP || 0) - (a.edgePP || 0));
    const tb = $("rows");
    if (!rows.length) { tb.innerHTML = '<tr><td colspan="7" class="empty">Noch keine Märkte — Pipeline erzeugt markets.json.</td></tr>'; }
    else {
      tb.innerHTML = rows.map(m => {
        const a = m.asset || "?";
        const col = coinColors[a] || "#888";
        const e = m.edgePP, eCls = e == null ? "dim" : (e > 0 ? "pos" : "neg");
        const eTxt = e == null ? "—" : (e > 0 ? "+" : "") + e.toFixed(1) + "pp";
        const gross = m.edgeGrossPP;
        const grossTxt = (gross != null && e != null) ? `<div class="grosslbl">brutto ${(gross > 0 ? "+" : "") + gross.toFixed(1)}</div>` : "";
        const spk = sparkline(trends[m.conditionId]);
        return `<tr>
          <td><span class="asset"><span class="coin" style="background:${col}">${a[0]}</span>${a}</span>
              <div class="mkt-sub">${esc(m.market)}</div></td>
          <td class="r num">${pct(m.polyPrice)}</td>
          <td class="r num">${pct(m.fairProb)}</td>
          <td class="r num">${m.ivPct != null ? m.ivPct.toFixed(0) + "%" : "—"}</td>
          <td>${spk}</td>
          <td class="r"><div class="edge-cell">${edgeBar(e)}<span><span class="edgeval ${eCls}">${eTxt}</span>${grossTxt}</span></div></td>
          <td class="r num">${usd(m.liquidityUSD)}</td>
        </tr>`;
      }).join("");
    }

    const ref = data.reference || {};
    $("refline").innerHTML =
      `<span>Referenz-Spot <b class="num">${ref.spot ? "$" + ref.spot.toLocaleString("de-DE") : "—"}</b></span>`
      + `<span>Quelle <b>${esc(ref.spotSource || "—")}</b></span>`
      + `<span>ATM-IV <b class="num">${ref.iv != null ? (ref.iv * 100).toFixed(0) + "%" : "—"}</b></span>`;
    if (data.generatedAt) $("updated").textContent = "Stand: " + data.generatedAt;
    if (data.note) $("disc").textContent = "cryptoedge · " + data.note;

    renderContext(data);
  }

  // ---- Kontext-Rail -----------------------------------------------------------------------
  function renderContext(data) {
    const fg = (data.context || {}).fearGreed;
    $("gauge").innerHTML = fg
      ? fgGauge(fg.value) + `<div class="gauge-val" style="color:${fg.value != null && fg.value < 45 ? "var(--warn)" : "var(--pos)"}">${fg.value ?? "—"}</div>`
        + `<div class="gauge-cls">Fear &amp; Greed · ${esc(fg.classification || "—")}</div>`
      : '<div class="mkt-sub">Fear &amp; Greed n/a</div>';

    const sigs = (data.contextSignals || []);
    $("csignals").innerHTML = sigs.length ? sigs.map(s => {
      const cls = s.silent ? "dim" : (s.adjPP > 0 ? "pos" : s.adjPP < 0 ? "neg" : "dim");
      const val = s.silent ? "—" : (s.adjPP > 0 ? "+" : "") + s.adjPP + "pp";
      return `<div class="csig"><div><div class="nm">${esc(s.name)}</div><div class="ev">${esc(s.evidence || s.family)}</div></div>`
        + `<span class="adj ${cls}">${val}</span></div>`;
    }).join("") : '<div class="ctx-note">Noch keine Kontext-Signale.</div>';
  }

  // ---- Laden ------------------------------------------------------------------------------
  const j = (u) => fetch(u + "?_=" + Date.now()).then(r => r.ok ? r.json() : Promise.reject(r.status));
  Promise.allSettled([j("markets.json"), j("clv.json")]).then(([mkt, clv]) => {
    const clvData = clv.status === "fulfilled" ? clv.value : {};
    renderKpis(clvData);
    if (mkt.status === "fulfilled") renderMarkets(mkt.value, (clvData.trends || {}));
    else $("rows").innerHTML = '<tr><td colspan="7" class="empty">markets.json noch nicht vorhanden.</td></tr>';
  });
})();
