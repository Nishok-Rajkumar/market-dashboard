# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""NSE Swing Screener.

Screens an NSE universe (default Nifty 500) for swing-trading candidates:

  * Minervini trend template (8 checks) + RS rating (1-99, percentile of weighted
    3/6/9/12-month return within the universe).
  * Setups:
      BREAKOUT_READY  in an uptrend, within 6% below a 40-session pivot high,
                      volatility contracting (ATR10/ATR50 < 0.8) and volume drying up.
      BREAKOUT_TODAY  closed above the prior 40-session high on >= 1.5x average volume.
      PULLBACK        in an uptrend, low tagged the 20- or 50-DMA in the last 3
                      sessions and close is back above it.
  * Liquidity filter: 20-day median traded value >= Rs 5 crore (configurable).
  * Each candidate gets an entry trigger, a structural stop and risk % to the stop.

Usage:
  uv run scripts/nse_swing_screener.py
  uv run scripts/nse_swing_screener.py --universe nifty200 --min-rs 80 --top 15
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

UNIVERSES = {
    "nifty50": "ind_nifty50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv",
    "midcap150": "ind_niftymidcap150list.csv",
    "smallcap250": "ind_niftysmallcap250list.csv",
}
NSE_ARCHIVE = "https://archives.nseindia.com/content/indices/"
CACHE_DIR = Path.home() / ".cache" / "nse-skills"
CRORE = 1e7


def load_constituents(universe: str) -> pd.DataFrame:
    fname = UNIVERSES[universe]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / fname
    if cached.exists() and time.time() - cached.stat().st_mtime < 7 * 86400:
        return pd.read_csv(cached)
    req = urllib.request.Request(NSE_ARCHIVE + fname, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except OSError as exc:
        if cached.exists():
            return pd.read_csv(cached)
        raise SystemExit(f"error: could not download {fname} from NSE: {exc}")
    cached.write_text(raw)
    return pd.read_csv(io.StringIO(raw))


def latest_breadth_zone(report_dir: Path) -> str | None:
    """Read the zone from the newest nse-breadth-analyzer JSON report, if any."""
    files = sorted(report_dir.glob("nse_breadth_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        r = json.loads(files[-1].read_text())
        return f"{r['zone']} (score {r['composite_score']}, {r['universe']}, {r['as_of']})"
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> float:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())


def evaluate(sym: str, o: pd.DataFrame, rs: float) -> dict | None:
    o = o.dropna()
    if len(o) < 220:
        return None
    c, h, l, v = o["Close"], o["High"], o["Low"], o["Volume"]
    close = float(c.iloc[-1])
    sma = {n: c.rolling(n).mean() for n in (20, 50, 150, 200)}
    s20, s50, s150, s200 = (float(sma[n].iloc[-1]) for n in (20, 50, 150, 200))
    hi52, lo52 = float(h.iloc[-252:].max()), float(l.iloc[-252:].min())

    checks = {
        "close_gt_150_200": close > s150 and close > s200,
        "sma150_gt_200": s150 > s200,
        "sma200_rising": s200 > float(sma[200].iloc[-22]),
        "sma50_gt_150_200": s50 > s150 and s50 > s200,
        "close_gt_50": close > s50,
        "25pct_above_52w_low": close >= 1.25 * lo52,
        "within_25pct_of_52w_high": close >= 0.75 * hi52,
        "rs_ge_70": rs >= 70,
    }
    tt_score = sum(checks.values())

    turnover_cr = float((c * v).iloc[-20:].median()) / CRORE
    vol50 = float(v.iloc[-50:].mean())
    vol_ratio_today = float(v.iloc[-1]) / vol50 if vol50 else 0.0
    vol_dryup = float(v.iloc[-10:].mean()) / vol50 if vol50 else 1.0
    atr10, atr50 = atr(h, l, c, 10), atr(h, l, c, 50)
    contraction = atr10 / atr50 if atr50 else 1.0

    pivot_prior = float(h.iloc[-41:-1].max())  # 40-session high excluding today
    pivot_incl = float(h.iloc[-40:].max())
    setups = []
    entry = stop = None

    if close > pivot_prior and vol_ratio_today >= 1.5 and tt_score >= 7:
        setups.append("BREAKOUT_TODAY")
        entry = close
        stop = max(float(l.iloc[-1]), pivot_prior - atr10)  # failed breakout = back below pivot
    elif tt_score >= 7 and 0 <= (pivot_incl - close) / pivot_incl <= 0.06 and contraction < 0.8 and vol_dryup < 1.0:
        setups.append("BREAKOUT_READY")
        entry = pivot_incl * 1.005
        stop = float(l.iloc[-10:].min())
    if tt_score >= 7 and not setups:
        for n, s in ((20, s20), (50, s50)):
            touched = float(l.iloc[-3:].min()) <= s * 1.01
            if touched and close > s:
                setups.append(f"PULLBACK_{n}DMA")
                entry = float(h.iloc[-1]) * 1.002
                stop = min(float(l.iloc[-3:].min()), s) - 0.5 * atr10
                break

    if not setups:
        return {"symbol": sym, "tt_score": tt_score, "rs": rs, "setup": None}

    risk_pct = (entry - stop) / entry * 100
    return {
        "symbol": sym,
        "setup": setups[0],
        "close": round(close, 2),
        "entry_trigger": round(entry, 2),
        "stop": round(stop, 2),
        "risk_pct": round(risk_pct, 2),
        "target_2r": round(entry + 2 * (entry - stop), 2),
        "rs": rs,
        "tt_score": tt_score,
        "pct_from_52w_high": round((close / hi52 - 1) * 100, 1),
        "atr_contraction": round(contraction, 2),
        "vol_vs_50d_today": round(vol_ratio_today, 2),
        "turnover_cr": round(turnover_cr, 1),
        "failed_checks": [k for k, ok in checks.items() if not ok],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE swing-trade screener.")
    ap.add_argument("--universe", choices=sorted(UNIVERSES), default="nifty500")
    ap.add_argument("--min-rs", type=float, default=70)
    ap.add_argument("--min-turnover-cr", type=float, default=5.0, help="20-day median traded value, Rs crore")
    ap.add_argument("--max-risk-pct", type=float, default=10.0, help="drop candidates with a wider stop")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--output-dir", default="reports/data")
    args = ap.parse_args()

    cons = load_constituents(args.universe)
    cons["Ticker"] = cons["Symbol"].str.strip() + ".NS"
    industry = dict(zip(cons["Ticker"], cons["Industry"]))
    tickers = cons["Ticker"].tolist()

    print(f"Downloading {len(tickers)} {args.universe} stocks ...", file=sys.stderr)
    data = yf.download(tickers, period="15mo", interval="1d", auto_adjust=True,
                       progress=False, threads=True, group_by="ticker")

    # RS rating: weighted 3/6/9/12-month return, percentile within the universe.
    closes = pd.DataFrame({t: data[t]["Close"] for t in tickers if t in data.columns.get_level_values(0)})
    closes = closes.ffill()
    valid = [t for t in closes.columns if closes[t].dropna().shape[0] >= 252]
    cl = closes[valid]
    perf = (0.4 * (cl.iloc[-1] / cl.iloc[-63] - 1) + 0.2 * (cl.iloc[-1] / cl.iloc[-126] - 1)
            + 0.2 * (cl.iloc[-1] / cl.iloc[-189] - 1) + 0.2 * (cl.iloc[-1] / cl.iloc[-252] - 1))
    rs_rating = (perf.rank(pct=True) * 98 + 1).round().astype(int)

    rows, tt_pass = [], 0
    for t in valid:
        r = evaluate(t.removesuffix(".NS"), data[t], int(rs_rating[t]))
        if r is None:
            continue
        tt_pass += r["tt_score"] >= 7
        if r["setup"] and r["rs"] >= args.min_rs and r["turnover_cr"] >= args.min_turnover_cr \
                and 0 < r["risk_pct"] <= args.max_risk_pct:
            r["industry"] = industry.get(t, "")
            rows.append(r)

    order = {"BREAKOUT_TODAY": 0, "BREAKOUT_READY": 1, "PULLBACK_20DMA": 2, "PULLBACK_50DMA": 3}
    rows.sort(key=lambda r: (order[r["setup"]], -r["rs"]))
    as_of = cl.index[-1].strftime("%Y-%m-%d")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    zone = latest_breadth_zone(out)

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of, "universe": args.universe, "stocks_scanned": len(valid),
        "trend_template_passes": int(tt_pass), "candidates": len(rows),
        "market_breadth_zone": zone,
        "filters": {k: getattr(args, k) for k in ("min_rs", "min_turnover_cr", "max_risk_pct")},
        "results": rows,
    }
    stem = f"nse_swing_{args.universe}_{as_of}"
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2))

    md = [f"# NSE Swing Screener — {args.universe.upper()} — {as_of}", "",
          f"- Scanned {len(valid)} stocks; {tt_pass} pass the trend template (>= 7/8); {len(rows)} actionable setups.",
          f"- Market breadth: **{zone or 'not available — run nse-breadth-analyzer first'}**", ""]
    by_setup: dict[str, list] = {}
    for r in rows:
        by_setup.setdefault(r["setup"], []).append(r)
    for setup, items in by_setup.items():
        md += [f"## {setup} ({len(items)})", "",
               "| Symbol | Industry | RS | Close | Entry | Stop | Risk % | 2R target | From 52w high % | Vol x50d | Turnover Cr |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in items[: args.top]:
            md.append(f"| {r['symbol']} | {r['industry']} | {r['rs']} | {r['close']} | {r['entry_trigger']} | {r['stop']} "
                      f"| {r['risk_pct']} | {r['target_2r']} | {r['pct_from_52w_high']} | {r['vol_vs_50d_today']} | {r['turnover_cr']} |")
        md.append("")
    md += ["_Candidates are a watchlist, not buy signals. Confirm on the chart, size with position-sizer, "
           "and pass the pre-trade discipline gate._"]
    (out / f"{stem}.md").write_text("\n".join(md) + "\n")

    print(f"JSON report: {out / (stem + '.json')}")
    print(f"Markdown report: {out / (stem + '.md')}")
    print(f"\n{len(rows)} setups ({tt_pass} trend-template passes) as of {as_of}. Breadth: {zone or 'n/a'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
