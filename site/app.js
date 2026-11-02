// Market Pulse India — reads the JSON written by pipeline/run_daily.py and renders the page.
// Served from GitHub Pages as /index.html + /data/…; locally from the repo root as /site/ + /data/.
const DATA = location.pathname.includes("/site/") ? "../data/" : "data/";
const $ = (id) => document.getElementById(id);
const charts = {};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null || isNaN(n) ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
const signed = (n, d = 2, suffix = "%") => (n == null ? "—" : `<span class="num ${n > 0 ? "up" : n < 0 ? "down" : ""}">${n > 0 ? "+" : ""}${fmt(n, d)}${suffix}</span>`);
const empty = (msg = "No data for this day.") => `<p class="empty">${esc(msg)}</p>`;

async function get(path) {
  try {
    const r = await fetch(DATA + path, { cache: "no-cache" });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function table(rows, cols) {
  if (!rows || !rows.length) return empty("None today.");
  const head = cols.map((c) => `<th class="${c.r ? "r" : ""}">${esc(c.h)}</th>`).join("");
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.r ? "r num" : ""}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("");
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function chart(id, config) {
  if (!window.Chart) return;
  charts[id]?.destroy();
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  charts[id] = new Chart($(id), config);
}

// ---------- explainers (ⓘ buttons) ----------

const GLOSSARY = {
  vix: ["India VIX", "The market's expected Nifty volatility over the next 30 days, from option prices. Below ~13 is calm, above ~20 is fearful. It usually rises when markets fall."],
  pivots: ["Pivot levels", "Calculated from the last session's high, low and close. P is the balance point; R1–R3 are resistance above, S1–S3 support below. Mostly used by intraday traders as reference points, not predictions."],
  heatmap: ["Nifty 50 heatmap", "Each box is a Nifty 50 company, grouped by industry. Box size = company size (market value), colour = today's % change: green up, red down. Big green boxes lift the index the most."],
  fii: ["FII and DII", "FII = Foreign Institutional Investors (overseas funds). DII = Domestic Institutional Investors (Indian mutual funds, insurers like LIC). Net = buy minus sell in the cash market, in ₹ crore. When FIIs sell heavily and DIIs absorb it, the index can stay steady even as foreigners exit."],
  streak: ["Streak", "How many sessions in a row the group has been net buyers (+) or net sellers (−)."],
  fiioi: ["FII index-futures positioning", "Of all the Nifty/Bank Nifty futures contracts FIIs hold, the share that are long (betting up). Near 50% is balanced. Below 20% means they are heavily short; such extremes are watched closely because short-covering can spark sharp rallies."],
  delivery: ["Delivery %", "The share of shares traded that were actually taken into demat accounts (held), not squared off the same day. A big jump in delivery with price up hints at genuine buying (accumulation); with price down, genuine selling."],
  ban: ["F&O ban", "When open interest in a stock's futures and options crosses 95% of the exchange limit, nobody can open new positions until it falls below 80%. Ban stocks can be volatile."],
  breadth: ["Market breadth", "Checks how many stocks are healthy, not just the index. The score (0–100) blends: % of Nifty 500 stocks above their 50- and 200-day averages, new 52-week highs vs lows, the trend of those numbers, Nifty's own trend and VIX. Above 60 = healthy, below 40 = weak."],
  dma: ["Moving average (DMA)", "The average closing price of the last N days. A stock above its 200-DMA is in a long-term uptrend; above its 50-DMA, a medium-term uptrend. When most stocks are below, the market is weak even if the index looks fine."],
  rrg: ["Sector rotation chart", "Each dot is a sector compared with the Nifty 500. Right of centre = stronger than the market (RS-Ratio above 100). Above centre = that strength is improving (RS-Momentum above 100). Sectors tend to move clockwise: Improving → Leading → Weakening → Lagging → Improving."],
  pcr: ["Put-Call Ratio (PCR)", "Total put open interest ÷ total call open interest. In India, option sellers dominate, so PCR above 1 means more puts are written — sellers expect support below. Above ~1.5 is crowded and can reverse fast if support breaks; below ~0.7 is bearish."],
  maxpain: ["Max pain", "The expiry price at which option buyers together lose the most money. Prices sometimes drift toward it near expiry, but it's a tendency, not a rule."],
  walls: ["OI walls", "Strikes with the most open interest. A big call wall often acts like resistance (sellers defend it), a big put wall like support."],
  expmove: ["Expected move", "Derived from the at-the-money straddle (call + put) price: the range the options market is pricing in until expiry, with roughly 2-in-3 odds of staying inside."],
  swing: ["Swing screener", "Looks for stocks in strong uptrends (Minervini trend template) that are near a buy point. RS = relative strength rating 1–99 (90 = beat 90% of stocks over the past year). Entry = price that must trade to trigger; Stop = where the idea is wrong; 2R = target twice the risk. Study material, not advice."],
};

function initExplainers() {
  const pop = $("pop");
  let openBtn = null;
  const close = () => { pop.hidden = true; openBtn?.setAttribute("aria-expanded", "false"); openBtn = null; };
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".info");
    if (!btn) { if (!e.target.closest("#pop")) close(); return; }
    if (btn === openBtn) return close();
    close();
    const [title, text] = GLOSSARY[btn.dataset.g] || ["", ""];
    pop.innerHTML = `<b>${esc(title)}</b>${esc(text)}`;
    pop.hidden = false;
    const r = btn.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left + scrollX - 12, scrollX + document.documentElement.clientWidth - pop.offsetWidth - 8));
    pop.style.left = left + "px";
    pop.style.top = r.bottom + scrollY + 6 + "px";
    btn.setAttribute("aria-expanded", "true");
    openBtn = btn;
  });
  document.addEventListener("keydown", (e) => e.key === "Escape" && close());
}
const info = (k) => `<button class="info" data-g="${k}" aria-label="Explain ${esc(GLOSSARY[k]?.[0] || k)}">i</button>`;

// ---------- sections ----------

function renderStatus(status, latest) {
  const s = status || {};
  const when = s.updated_at ? new Date(s.updated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }) : "unknown";
  const ageH = s.updated_at ? (Date.now() - new Date(s.updated_at)) / 36e5 : 999;
  const badge = ageH < 30 ? `<span class="badge good">fresh</span>` : `<span class="badge mid">${Math.round(ageH / 24)}d old</span>`;
  $("updated").innerHTML = `Updated ${esc(when)} IST ${badge}`;
  const failed = Object.entries(s.steps || {}).filter(([, v]) => !v.ok).map(([k]) => k);
  const sectionErr = Object.keys(s.steps?.pulse?.section_errors || {});
  const msgs = [];
  if (failed.length) msgs.push(`Some sources failed on this run: <b>${failed.map(esc).join(", ")}</b>. Those sections may be empty.`);
  if (sectionErr.length) msgs.push(`Partial data in pulse: ${sectionErr.map(esc).join(", ")}.`);
  $("alerts").innerHTML = msgs.map((m) => `<div class="alert">${m}</div>`).join("");
}

function renderSummary(sum) {
  $("summary").textContent = sum?.text || "No summary for this day.";
  const by = sum?.model === "rule-based" ? "Auto-written from the numbers (no AI model reachable)" : `Written by ${sum?.model}`;
  $("summary-model").textContent = sum ? `${by}. For learning only, not investment advice.` : "";
}

function renderSnapshot(pulse, levels) {
  const snap = Array.isArray(pulse?.snapshot) ? pulse.snapshot : [];
  $("tiles").innerHTML = snap.length ? snap.map((s) => `
    <div class="tile"><div class="label">${esc(s.name)}</div>
      <div class="value num">${fmt(s.last, s.last < 200 ? 2 : 0)}</div>
      <div class="chg">1D ${signed(s.chg_1d_pct)} · 5D ${signed(s.chg_5d_pct)}</div></div>`).join("") : empty();

  const lv = Object.values(levels || {});
  $("pivots").innerHTML = lv.map((v) => `
    <div class="card"><h3>${esc(v.name)} levels <span class="muted small">floor pivots from ${esc(v.date)}</span> ${info("pivots")}</h3>
      ${table([v], ["S3", "S2", "S1", "P", "R1", "R2", "R3"].map((k) => ({ h: k, r: 1, f: (r) => (k === "P" ? `<b>${fmt(r[k])}</b>` : fmt(r[k])) })))}
      <p class="small muted" style="margin:10px 0 0">Close ${fmt(v.C)} · 50-DMA ${fmt(v.dma50)} · 200-DMA ${fmt(v.dma200)} ·
        ${signed(v.from_high, 1)} from 52-week high</p></div>`).join("");
}

function renderFlows(pulse, history) {
  const f = pulse?.fii_dii;
  if (!f || f.error) {
    $("fii-cards").innerHTML = `<h3>FII / DII</h3>${empty(f?.error ? "Unavailable: " + f.error : undefined)}`;
  } else {
    const latest = Object.fromEntries(f.latest.map((x) => [x.category, x]));
    const block = (c) => `<div><span>${c} net · ${esc(latest[c]?.date || "")}</span><b>${signed(latest[c]?.net_cr, 0, "")}</b>
      <span>5d ${fmt(f[c].sum_5d_cr)} · 20d ${fmt(f[c].sum_20d_cr)} · streak ${f[c].streak_days > 0 ? "+" : ""}${f[c].streak_days}d</span></div>`;
    $("fii-cards").innerHTML = `<h3>FII / DII latest ${info("streak")}</h3><div class="kv">${block("FII")}${block("DII")}</div>
      ${["FII", "DII"].map((c) => flowContext(c, latest[c], history)).join("")}`;
  }
  renderCalendar(history);
  const h = (history || []).slice(-120);
  const dates = [...new Set(h.map((r) => r.date))].slice(-60);
  const series = (cat) => dates.map((d) => h.find((r) => r.date === d && r.category === cat)?.net_cr ?? null);
  chart("fii-chart", {
    type: "bar",
    data: { labels: dates.map((d) => d.slice(5)), datasets: [
      { label: "FII", data: series("FII"), backgroundColor: css("--down") },
      { label: "DII", data: series("DII"), backgroundColor: css("--accent") }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } }, scales: { y: { ticks: { callback: (v) => fmt(v) } } } },
  });

  const d = pulse?.delivery || {};
  const cols = [{ h: "Symbol", k: "symbol" }, { h: "Close", r: 1, f: (r) => fmt(r.close, 1) }, { h: "Chg", r: 1, f: (r) => signed(r.chg_pct) },
    { h: "Deliv %", r: 1, f: (r) => fmt(r.deliv_pct, 0) }, { h: "× 10d avg", r: 1, f: (r) => fmt(r.deliv_x_avg10, 1) }];
  $("accum").innerHTML = d.error ? empty(d.error) : table(d.accumulation, cols);
  $("distrib").innerHTML = d.error ? empty(d.error) : table(d.distribution, cols);
  const mv = [{ h: "Symbol", k: "symbol" }, { h: "Industry", f: (r) => `<span class="muted">${esc(r.industry || "")}</span>` },
    { h: "Close", r: 1, f: (r) => fmt(r.close, 1) }, { h: "Chg", r: 1, f: (r) => signed(r.chg_pct) }];
  $("gainers").innerHTML = d.error ? empty(d.error) : table(d.top_gainers, mv);
  $("losers").innerHTML = d.error ? empty(d.error) : table(d.top_losers, mv);

  const ban = pulse?.fo_ban;
  $("ban").innerHTML = !ban || ban.error ? empty(ban?.error) :
    `<p class="small muted">${esc(ban.header)}</p><p>${ban.symbols.length ? ban.symbols.map(esc).join(", ") : "No stocks in ban today."}</p>
     <p class="small muted">Stocks in ban can't take new F&amp;O positions — open interest crossed 95% of the limit.</p>`;
  const ev = pulse?.upcoming_results;
  $("events").innerHTML = !Array.isArray(ev) ? empty(ev?.error ? "Unavailable: " + ev.error : undefined) :
    table(ev.slice(0, 40), [{ h: "Date", k: "date" }, { h: "Symbol", k: "symbol" }, { h: "Purpose", f: (r) => `<span class="muted">${esc(r.purpose)}</span>` }]);
}

// Today's flow against our own history: average, rank, month-to-date.
function flowContext(cat, today, history) {
  if (!today || !history?.length) return "";
  const rows = history.filter((r) => r.category === cat && r.date <= today.date);
  const nets = rows.map((r) => r.net_cr);
  if (nets.length < 3) return "";
  const last20 = nets.slice(-20);
  const avg = last20.reduce((a, b) => a + b, 0) / last20.length;
  const absRank = [...last20].sort((a, b) => Math.abs(b) - Math.abs(a)).indexOf(today.net_cr) + 1;
  const month = today.date.slice(0, 7);
  const mtd = rows.filter((r) => r.date.startsWith(month)).reduce((a, r) => a + r.net_cr, 0);
  const since = rows[0].date;
  return `<p class="ctx"><b>${cat}</b>: today ${signed(today.net_cr, 0, "")} vs ${last20.length}-session avg ${signed(avg, 0, "")} ·
    ${absRank === 1 ? "<b>biggest move</b>" : `#${absRank} biggest move`} of the last ${last20.length} ·
    month to date ${signed(mtd, 0, "")}${since > month ? ` (since ${since.slice(5)})` : ""}</p>`;
}

function renderCalendar(history) {
  const h = history || [];
  if (!h.length) { $("flow-calendar").innerHTML = empty(); return; }
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const grid = (cat) => {
    const rows = h.filter((r) => r.category === cat).slice(-65);
    const byDate = Object.fromEntries(rows.map((r) => [r.date, r.net_cr]));
    const max = Math.max(...rows.map((r) => Math.abs(r.net_cr)), 1);
    // One square per weekday from the Monday of the first week to the last session; blank = holiday or no data.
    const d = new Date(rows[0].date + "T00:00");
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    const end = rows[rows.length - 1].date, cells = [];
    for (; iso(d) <= end; d.setDate(d.getDate() + 1)) {
      if (d.getDay() === 0 || d.getDay() === 6) continue;
      const k = iso(d), v = byDate[k];
      if (v == null) { cells.push(`<i title="${k}: no data"></i>`); continue; }
      const a = 0.18 + 0.82 * Math.abs(v) / max;
      cells.push(`<i style="background:${v >= 0 ? css("--up") : css("--down")};opacity:${a.toFixed(2)}" title="${k}: ${v >= 0 ? "+" : ""}${fmt(v)} Cr"></i>`);
    }
    return `<div><div class="cal-title">${cat} — ${rows.length} sessions recorded</div><div class="cal">${cells.join("")}</div></div>`;
  };
  $("flow-calendar").innerHTML = grid("FII") + grid("DII") +
    `<p class="cal-legend">Green = net buying, red = net selling. Rows are Mon–Fri. Hover a square for the amount. The history grows by one square every trading day.</p>`;
}

function renderPOI(po) {
  if (!po?.clients) { $("poi-card").innerHTML = `<h3>F&amp;O positioning</h3>${empty()}`; chart("poi-chart", { type: "line", data: { datasets: [] } }); return; }
  const f = po.clients.FII;
  const tone = f.fut_idx_long_pct < 35 ? "bad" : f.fut_idx_long_pct > 60 ? "good" : "mid";
  const row = (c) => { const x = po.clients[c]; return { c, ...x }; };
  $("poi-card").innerHTML = `<h3>F&amp;O positioning by participant <span class="muted small">as of ${esc(po.as_of)}</span> ${info("fiioi")}</h3>
    <div class="kv">
      <div><b class="num"><span class="badge ${tone}">${fmt(f.fut_idx_long_pct, 1)}% long</span></b><span>FII index futures</span></div>
      <div><b class="num">${signed(f.fut_idx_net, 0, "")}</b><span>FII net contracts</span></div>
      <div><b class="num">${signed(f.fut_idx_net_chg, 0, "")}</b><span>change vs prev session</span></div>
    </div>
    <p class="small" style="margin:10px 0 4px">${esc(po.fii_read)}</p>
    <p class="small muted" style="margin:0 0 10px">Today's long share is higher than ${po.fii_pct_rank}% of the last ${po.sessions} sessions.</p>
    ${table(["FII", "DII", "Pro", "Client"].map(row), [
      { h: "Who", f: (r) => `<b>${r.c}</b>` },
      { h: "Index fut % long", r: 1, f: (r) => fmt(r.fut_idx_long_pct, 1) + "%" },
      { h: "Index fut net", r: 1, f: (r) => signed(r.fut_idx_net, 0, "") },
      { h: "Index calls net", r: 1, f: (r) => signed(r.idx_call_net, 0, "") },
      { h: "Index puts net", r: 1, f: (r) => signed(r.idx_put_net, 0, "") }])}
    <p class="small muted" style="margin:8px 0 0">Pro = brokers trading their own money · Client = retail and HNIs. Net = long − short contracts.</p>`;
  const h = po.fii_history || [];
  chart("poi-chart", {
    type: "line",
    data: { labels: h.map((r) => r.date.slice(5)), datasets: [
      { label: "FII % long", data: h.map((r) => r.fut_idx_long_pct), borderColor: css("--accent"), backgroundColor: css("--accent"), tension: .3, pointRadius: 2, fill: false }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { y: { suggestedMin: 0, suggestedMax: 60, ticks: { callback: (v) => v + "%" } } } },
  });
}

let heatChart = null;
function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
}
function renderHeatmap(h) {
  const el = $("heatmap");
  if (!window.echarts) return;
  heatChart?.dispose();
  heatChart = null;
  if (!h?.stocks?.length) { el.innerHTML = empty("Heatmap not available for this day."); $("heatmap-meta").textContent = ""; return; }
  el.innerHTML = "";
  $("heatmap-meta").textContent = `as of ${h.as_of} · size = ${h.size_by === "market_cap" ? "market value" : "traded value"}`;
  const neutral = css("--surface-2"), up = css("--up"), down = css("--down");
  const colour = (c) => (c >= 0 ? mix(neutral, up, Math.min(1, c / 3)) : mix(neutral, down, Math.min(1, -c / 3)));
  const groups = {};
  h.stocks.forEach((s) => (groups[s.industry] ||= []).push(s));
  const data = Object.entries(groups).map(([ind, list]) => ({
    name: ind,
    children: list.map((s) => ({ name: s.symbol, value: s.size, chg: s.chg_pct, close: s.close, full: s.name, ind,
      itemStyle: { color: colour(s.chg_pct) } })),
  }));
  heatChart = echarts.init(el, null, { renderer: "canvas" });
  heatChart.setOption({
    tooltip: { formatter: (p) => p.data.chg == null ? esc(p.name) :
      `<b>${esc(p.data.full)}</b><br>${esc(p.data.ind)}<br>${esc(p.name)} · ₹${fmt(p.data.close, 2)} · ${p.data.chg > 0 ? "+" : ""}${fmt(p.data.chg, 2)}%` },
    series: [{
      type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, width: "100%", height: "100%",
      top: 0, left: 0, right: 0, bottom: 0, data,
      label: { show: true, formatter: (p) => `${p.name}\n${p.data.chg > 0 ? "+" : ""}${fmt(p.data.chg, 2)}%`,
        color: css("--text"), fontFamily: "Inter", fontSize: 12, lineHeight: 15 },
      upperLabel: { show: false },
      levels: [
        { itemStyle: { borderColor: css("--bg"), borderWidth: 0, gapWidth: 3 } },
        { itemStyle: { borderColor: css("--bg"), borderWidth: 3, gapWidth: 3 } },
        { itemStyle: { borderColor: css("--bg"), borderWidth: 1, gapWidth: 1 } },
      ],
    }],
  });
}

// Plugin for the rotation chart: shaded quadrants and sector names at each latest point.
const rrgPlugin = {
  id: "rrg",
  beforeDatasetsDraw(c) {
    const { ctx, chartArea: a, scales: { x, y } } = c;
    const cx = x.getPixelForValue(100), cy = y.getPixelForValue(100);
    const q = [["IMPROVING", a.left, a.top, cx - a.left, cy - a.top, "--warn"], ["LEADING", cx, a.top, a.right - cx, cy - a.top, "--up"],
      ["LAGGING", a.left, cy, cx - a.left, a.bottom - cy, "--down"], ["WEAKENING", cx, cy, a.right - cx, a.bottom - cy, "--warn"]];
    ctx.save();
    q.forEach(([label, l, t, w, h, col]) => {
      ctx.globalAlpha = 0.07; ctx.fillStyle = css(col); ctx.fillRect(l, t, w, h);
      ctx.globalAlpha = 0.7; ctx.font = "600 11px Inter"; ctx.fillStyle = css(col);
      ctx.textAlign = l === a.left ? "left" : "right";
      ctx.textBaseline = t === a.top ? "top" : "bottom";
      ctx.fillText(label, l === a.left ? l + 6 : l + w - 6, t === a.top ? t + 6 : t + h - 6);
    });
    ctx.restore();
  },
  afterDatasetsDraw(c) {
    const { ctx } = c;
    ctx.save();
    ctx.font = "500 11px Inter"; ctx.fillStyle = css("--text"); ctx.textAlign = "left"; ctx.textBaseline = "middle";
    c.data.datasets.forEach((d, i) => {
      const meta = c.getDatasetMeta(i);
      const p = meta.data[meta.data.length - 1];
      if (p && !meta.hidden) ctx.fillText(d.label, p.x + 7, p.y);
    });
    ctx.restore();
  },
};
function renderRRG(s) {
  const all = (s?.sectors || []).filter((x) => x.trail_xy);
  const trails = $("rrg-trails").checked;
  const qc = { LEADING: "--up", IMPROVING: "--warn", WEAKENING: "--warn", LAGGING: "--down" };
  chart("rrg-chart", {
    type: "scatter",
    data: { datasets: all.map((x) => {
      const pts = (trails ? x.trail_xy : x.trail_xy.slice(-1)).map(([a, b]) => ({ x: a, y: b }));
      const col = css(qc[x.quadrant]);
      return { label: x.sector, data: pts, showLine: trails, borderColor: col + "99", backgroundColor: col, borderWidth: 1.5,
        pointRadius: pts.map((_, i) => (i === pts.length - 1 ? 5 : 2)), tension: .3 };
    }) },
    options: {
      maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (t) => `${t.dataset.label}: RS ${t.parsed.x.toFixed(1)}, momentum ${t.parsed.y.toFixed(1)}` } } },
      scales: { x: { title: { display: true, text: "RS-Ratio (strength vs Nifty 500) →" } },
        y: { title: { display: true, text: "RS-Momentum ↑" } } },
    },
    plugins: [rrgPlugin],
  });
}

// "What changed": compare the chosen day with the previous one in the index.
function renderChanges(cur, prev, prevDay) {
  const out = [];
  const add = (ico, html) => out.push(`<li><span class="ico">${ico}</span><span>${html}</span></li>`);
  const arrow = (d) => (d > 0 ? "▲" : d < 0 ? "▼" : "•");
  const nC = cur.levels?.["^NSEI"], nP = prev.levels?.["^NSEI"];
  if (nC && nP && nC.date !== nP.date) add(arrow(nC.C - nP.C), `Nifty ${fmt(nP.C)} → <b>${fmt(nC.C)}</b> (${signed((nC.C / nP.C - 1) * 100)})`);
  const bC = cur.breadth, bP = prev.breadth;
  if (bC && bP) {
    const d = bC.composite_score - bP.composite_score;
    add(arrow(d), `Breadth ${fmt(bP.composite_score, 1)} → <b>${fmt(bC.composite_score, 1)}</b>` +
      (bC.zone !== bP.zone ? ` — zone changed <b>${esc(bP.zone)} → ${esc(bC.zone)}</b>` : ` (${esc(bC.zone)})`));
  }
  const vC = cur.pulse?.snapshot?.find?.((x) => x.name === "India VIX"), vP = prev.pulse?.snapshot?.find?.((x) => x.name === "India VIX");
  if (vC && vP) add(arrow(vC.last - vP.last), `India VIX ${fmt(vP.last, 2)} → <b>${fmt(vC.last, 2)}</b>`);
  const fC = cur.pulse?.fii_dii?.FII;
  if (fC) add(fC.streak_days > 0 ? "▲" : "▼", `FIIs: ${Math.abs(fC.streak_days)}-session ${fC.streak_days > 0 ? "buying" : "selling"} streak`);
  const oC = cur.ocN, oP = prev.ocN;
  if (oC && oP) add(arrow(oC.pcr_oi_total - oP.pcr_oi_total), `Nifty PCR ${fmt(oP.pcr_oi_total, 2)} → <b>${fmt(oC.pcr_oi_total, 2)}</b>, max pain ${fmt(oP.max_pain)} → <b>${fmt(oC.max_pain)}</b>`);
  const sP = Object.fromEntries((prev.sectors?.sectors || []).map((x) => [x.sector, x.quadrant]));
  const moved = (cur.sectors?.sectors || []).filter((x) => sP[x.sector] && sP[x.sector] !== x.quadrant);
  if (moved.length) add("↻", `Sectors moved: ${moved.slice(0, 6).map((x) => `${esc(x.sector)} <span class="muted">${sP[x.sector][0] + sP[x.sector].slice(1).toLowerCase()} →</span> <b>${x.quadrant[0] + x.quadrant.slice(1).toLowerCase()}</b>`).join(", ")}${moved.length > 6 ? ` +${moved.length - 6} more` : ""}`);
  else if (cur.sectors && prev.sectors) add("•", "No sector changed quadrant.");
  const wC = new Set((cur.swing?.results || []).map((x) => x.symbol)), wP = new Set((prev.swing?.results || []).map((x) => x.symbol));
  if (cur.swing && prev.swing) {
    const added = [...wC].filter((x) => !wP.has(x)), gone = [...wP].filter((x) => !wC.has(x));
    add("★", `Swing list: <b>${added.length}</b> new${added.length ? ` (${added.slice(0, 5).map(esc).join(", ")}${added.length > 5 ? "…" : ""})` : ""}, ${gone.length} dropped`);
  }
  $("changes-vs").textContent = prevDay ? `vs ${new Date(prevDay + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}` : "";
  $("changes-list").innerHTML = out.join("") || `<li>${empty(prevDay ? "Not enough data on both days to compare." : "No earlier day to compare with yet.")}</li>`;
}

function renderBreadth(b) {
  if (!b) { $("breadth-score").innerHTML = `<h3>Breadth score</h3>${empty()}`; return; }
  const cls = b.composite_score >= 60 ? "good" : b.composite_score >= 40 ? "mid" : "bad";
  const x = b.breadth || {};
  $("breadth-score").innerHTML = `
    <h3>Breadth score <span class="badge ${cls}">${esc(b.zone)}</span></h3>
    <div class="num" style="font-size:32px;font-weight:600">${fmt(b.composite_score, 1)}<span class="muted" style="font-size:16px"> / 100</span></div>
    <div class="gauge"><i style="width:${Math.min(100, b.composite_score)}%"></i></div>
    <p class="small">${esc(b.guidance)}</p>
    <div class="kv">
      <div><b class="num">${fmt(x.pct_above_50dma, 1)}%</b><span>above 50-DMA</span></div>
      <div><b class="num">${fmt(x.pct_above_200dma, 1)}%</b><span>above 200-DMA</span></div>
      <div><b class="num"><span class="up">${x.advances}</span> / <span class="down">${x.declines}</span></b><span>advances / declines</span></div>
      <div><b class="num">${x.new_52w_highs} / ${x.new_52w_lows}</b><span>52w highs / lows</span></div>
    </div>
    <p class="small muted">Suggested equity exposure band: <b>${esc(b.suggested_equity_exposure)}</b> (a rule of thumb, not advice).</p>`;
  const h = b.history_30d || [];
  chart("breadth-chart", {
    type: "line",
    data: { labels: h.map((r) => r.date.slice(5)), datasets: [
      { label: "20-DMA", data: h.map((r) => r.pct_above_20dma), borderColor: css("--warn"), tension: .3, pointRadius: 0 },
      { label: "50-DMA", data: h.map((r) => r.pct_above_50dma), borderColor: css("--accent"), tension: .3, pointRadius: 0 },
      { label: "200-DMA", data: h.map((r) => r.pct_above_200dma), borderColor: css("--down"), tension: .3, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" } }, scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } } },
  });
}

function renderSectors(s) {
  const all = s?.sectors || [];
  if (!all.length) { $("quads").innerHTML = `<div class="card">${empty()}</div>`; return; }
  const meta = { LEADING: ["good", "strong and getting stronger"], IMPROVING: ["mid", "weak but turning up"],
    WEAKENING: ["mid", "strong but fading"], LAGGING: ["bad", "weak and getting weaker"] };
  $("quads").innerHTML = Object.entries(meta).map(([q, [cls, hint]]) => {
    const rows = all.filter((x) => x.quadrant === q).sort((a, b) => b.ret_1m - a.ret_1m);
    return `<div class="card quad"><h3><span class="badge ${cls}">${q}</span><span class="muted small">${hint}</span></h3>
      <ul>${rows.map((x) => `<li><span>${esc(x.sector)}</span><span class="small">1W ${signed(x.ret_1w, 1)} · 1M ${signed(x.ret_1m, 1)}</span></li>`).join("") || "<li class='muted'>none</li>"}</ul></div>`;
  }).join("");
}

function renderOptions(list) {
  const cards = list.filter(Boolean).map((o) => {
    const walls = (arr, k) => (arr || []).slice(0, 3).map((x) => `${fmt(x.strike)} <span class="muted">(${fmt(x[k] / 1e5, 1)}L)</span>`).join(", ");
    return `<div class="card"><h3>${esc(o.symbol)} · expiry ${esc(o.expiry)} <span class="muted small">${o.days_to_expiry} days left</span></h3>
      <div class="kv">
        <div><b class="num">${fmt(o.spot, 0)}</b><span>spot</span></div>
        <div><b class="num">${fmt(o.pcr_oi_total, 2)}</b><span>PCR (put/call OI)</span></div>
        <div><b class="num">${fmt(o.max_pain, 0)}</b><span>max pain ${info("maxpain")}</span></div>
        <div><b class="num">±${fmt(o.expected_move_pts, 0)}</b><span>expected move ${info("expmove")}</span></div>
      </div>
      <p class="small" style="margin:12px 0 4px">Expected range to expiry: <b class="num">${fmt(o.expected_range?.[0])} – ${fmt(o.expected_range?.[1])}</b></p>
      <p class="small" style="margin:4px 0"><span class="down">Call walls (resistance):</span> ${walls(o.resistance_call_oi, "ce_oi")} ${info("walls")}</p>
      <p class="small" style="margin:4px 0"><span class="up">Put walls (support):</span> ${walls(o.support_put_oi, "pe_oi")}</p>
      <p class="small muted" style="margin:8px 0 0">${esc(o.pcr_bias)} · data ${esc(o.data_timestamp)}</p></div>`;
  });
  $("oc").innerHTML = cards.join("") || `<div class="card">${empty("Option chain unavailable for this day (NSE may block cloud servers).")}</div>`;
}

function renderSwing(s) {
  if (!s) { $("swing-meta").textContent = ""; $("swing-table").innerHTML = empty(); return; }
  $("swing-meta").textContent = `${s.candidates} candidates from ${s.stocks_scanned} stocks (as of ${s.as_of}). Market: ${s.market_breadth_zone}. ` +
    "Entry = price that must trade to trigger; stop = where the idea is wrong; 2R = target at twice the risk.";
  $("swing-table").innerHTML = table(s.results, [
    { h: "Symbol", f: (r) => `<b>${esc(r.symbol)}</b>` }, { h: "Setup", f: (r) => `<span class="badge mid">${esc(r.setup.replace(/_/g, " "))}</span>` },
    { h: "Industry", f: (r) => `<span class="muted">${esc(r.industry || "")}</span>` },
    { h: "Close", r: 1, f: (r) => fmt(r.close, 1) }, { h: "Entry", r: 1, f: (r) => fmt(r.entry_trigger, 1) },
    { h: "Stop", r: 1, f: (r) => fmt(r.stop, 1) }, { h: "Risk", r: 1, f: (r) => fmt(r.risk_pct, 1) + "%" },
    { h: "2R target", r: 1, f: (r) => fmt(r.target_2r, 1) }, { h: "RS", r: 1, k: "rs" }]);
}

let newsItems = [], newsTag = "All";
function renderNews(n) {
  newsItems = n?.items || [];
  const counts = {};
  newsItems.forEach((i) => i.tags.forEach((t) => (counts[t] = (counts[t] || 0) + 1)));
  const tags = ["All", ...Object.keys(counts).sort((a, b) => (a === "Other") - (b === "Other") || counts[b] - counts[a])];
  if (!tags.includes(newsTag)) newsTag = "All";
  $("news-tags").innerHTML = tags.map((t) => `<button aria-pressed="${t === newsTag}" data-tag="${esc(t)}">${esc(t)}${t === "All" ? "" : ` <span class="muted">${counts[t]}</span>`}</button>`).join("");
  $("news-tags").querySelectorAll("button").forEach((b) => (b.onclick = () => { newsTag = b.dataset.tag; renderNews(n); }));
  const list = newsItems.filter((i) => newsTag === "All" || i.tags.includes(newsTag)).slice(0, 80);
  $("news-list").innerHTML = list.map((i) => {
    const t = i.published ? new Date(i.published).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "";
    const href = /^https?:\/\//.test(i.link) ? i.link : "#";
    return `<li><a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a>
      <div class="meta">${esc(i.source)} · ${esc(t)} · ${i.tags.map(esc).join(", ")}</div></li>`;
  }).join("") || `<li>${empty("No headlines.")}</li>`;
  const src = Object.entries(n?.sources || {});
  $("news-sources").textContent = src.length ? "Feeds: " + src.map(([k, v]) => `${k} ${v.ok ? "✓" : "✗"}`).join(" · ") : "";
}

// ---------- boot ----------

const COMPARE = { levels: "levels.json", breadth: "breadth.json", pulse: "pulse.json", ocN: "oc_NIFTY.json", sectors: "sectors.json", swing: "swing.json" };
async function loadCompare(day) {
  const vals = await Promise.all(Object.values(COMPARE).map((f) => get(`${day}/${f}`)));
  return Object.fromEntries(Object.keys(COMPARE).map((k, i) => [k, vals[i]]));
}

let days = [], current = {};
async function loadDay(day) {
  const p = (f) => get(`${day}/${f}`);
  const prevDay = days[days.indexOf(day) + 1];  // days are newest first
  const [status, summary, pulse, levels, breadth, sectors, ocN, ocB, swing, news, fii, poi, heat, prev] = await Promise.all([
    p("status.json"), p("summary.json"), p("pulse.json"), p("levels.json"), p("breadth.json"), p("sectors.json"),
    p("oc_NIFTY.json"), p("oc_BANKNIFTY.json"), p("swing.json"), p("news.json"), get("fii_dii_history.json"),
    p("participant_oi.json"), p("heatmap.json"), prevDay ? loadCompare(prevDay) : Promise.resolve({})]);
  current = { sectors, heat };
  renderStatus(status);
  renderSummary(summary);
  renderChanges({ levels, breadth, pulse, ocN, sectors, swing }, prev, prevDay);
  renderSnapshot(pulse, levels);
  renderHeatmap(heat);
  renderFlows(pulse, fii);
  renderPOI(poi);
  renderBreadth(breadth);
  renderSectors(sectors);
  renderRRG(sectors);
  renderOptions([ocN, ocB]);
  renderSwing(swing);
  renderNews(news);
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch {}
    loadDay($("day").value);  // redraw charts in the new colours
  };
}

(async function main() {
  initTheme();
  initExplainers();
  $("rrg-trails").onchange = () => renderRRG(current.sectors);
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => heatChart?.resize(), 150); });
  const [index, latest] = await Promise.all([get("index.json"), get("latest.json")]);
  days = (index?.days || []).slice().reverse();
  if (!days.length) { $("updated").textContent = "No data yet — run the pipeline once."; return; }
  $("day").innerHTML = days.map((d) => `<option value="${esc(d)}">${esc(new Date(d + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" }))}</option>`).join("");
  $("day").value = latest?.date && days.includes(latest.date) ? latest.date : days[0];
  $("day").onchange = () => loadDay($("day").value);
  await loadDay($("day").value);
})();
