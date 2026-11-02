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
    <div class="card"><h3>${esc(v.name)} levels <span class="muted small">floor pivots from ${esc(v.date)}</span></h3>
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
    $("fii-cards").innerHTML = `<h3>FII / DII latest</h3><div class="kv">${block("FII")}${block("DII")}</div>
      <p class="small muted">FII = foreign investors, DII = Indian funds/insurers. A positive streak means buying day after day.
      History: ${f.history_days} days.</p>`;
  }
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
        <div><b class="num">${fmt(o.max_pain, 0)}</b><span>max pain</span></div>
        <div><b class="num">±${fmt(o.expected_move_pts, 0)}</b><span>expected move</span></div>
      </div>
      <p class="small" style="margin:12px 0 4px">Expected range to expiry: <b class="num">${fmt(o.expected_range?.[0])} – ${fmt(o.expected_range?.[1])}</b></p>
      <p class="small" style="margin:4px 0"><span class="down">Call walls (resistance):</span> ${walls(o.resistance_call_oi, "ce_oi")}</p>
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

async function loadDay(day) {
  const p = (f) => get(`${day}/${f}`);
  const [status, summary, pulse, levels, breadth, sectors, ocN, ocB, swing, news, fii] = await Promise.all([
    p("status.json"), p("summary.json"), p("pulse.json"), p("levels.json"), p("breadth.json"), p("sectors.json"),
    p("oc_NIFTY.json"), p("oc_BANKNIFTY.json"), p("swing.json"), p("news.json"), get("fii_dii_history.json")]);
  renderStatus(status);
  renderSummary(summary);
  renderSnapshot(pulse, levels);
  renderFlows(pulse, fii);
  renderBreadth(breadth);
  renderSectors(sectors);
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
  const [index, latest] = await Promise.all([get("index.json"), get("latest.json")]);
  const days = (index?.days || []).slice().reverse();
  if (!days.length) { $("updated").textContent = "No data yet — run the pipeline once."; return; }
  $("day").innerHTML = days.map((d) => `<option value="${esc(d)}">${esc(new Date(d + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" }))}</option>`).join("");
  $("day").value = latest?.date && days.includes(latest.date) ? latest.date : days[0];
  $("day").onchange = () => loadDay($("day").value);
  await loadDay($("day").value);
})();
