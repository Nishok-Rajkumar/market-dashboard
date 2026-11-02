# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""NSE Breadth Analyzer.

Scores Indian market breadth (0-100, 100 = broad, healthy participation) from
the current constituents of an NSE index universe (default Nifty 500), using
free NSE constituent lists and Yahoo Finance end-of-day prices.

Components (weight):
  1. % of stocks above 200-DMA                  (25)  long-term participation
  2. % of stocks above 50-DMA                   (20)  medium-term participation
  3. 10-session change in % above 50-DMA        (15)  breadth momentum
  4. 52-week new highs vs new lows              (15)  leadership
  5. Nifty 50 position vs its 50/200-DMA        (15)  index trend
  6. India VIX level                            (10)  fear gauge

Usage:
  uv run scripts/nse_breadth.py                       # Nifty 500, reports/ in cwd
  uv run scripts/nse_breadth.py --universe nifty200 --output-dir reports
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
NIFTY = "^NSEI"
VIX = "^INDIAVIX"
CACHE_DIR = Path.home() / ".cache" / "nse-breadth-analyzer"
LIST_CACHE_DAYS = 7

WEIGHTS = {
    "pct_above_200dma": 25,
    "pct_above_50dma": 20,
    "breadth_momentum": 15,
    "new_highs_lows": 15,
    "index_trend": 15,
    "india_vix": 10,
}

ZONES = [
    (80, "STRONG", "80-100%", "Broad participation. Full swing allocation allowed; press winners."),
    (60, "HEALTHY", "60-80%", "Most stocks trending. Normal position sizes; new breakouts OK."),
    (40, "NEUTRAL", "40-60%", "Mixed tape. Be selective, smaller size, only A+ setups."),
    (20, "WEAK", "20-40%", "Narrow/declining breadth. Mostly cash; protect open gains."),
    (0, "CRITICAL", "0-20%", "Broad breakdown. No new longs; focus on capital preservation."),
]


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def load_constituents(universe: str) -> pd.DataFrame:
    """Download (or read cached) NSE constituent CSV: Company Name, Industry, Symbol."""
    fname = UNIVERSES[universe]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / fname
    if cached.exists() and time.time() - cached.stat().st_mtime < LIST_CACHE_DAYS * 86400:
        return pd.read_csv(cached)
    req = urllib.request.Request(NSE_ARCHIVE + fname, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except OSError as exc:
        if cached.exists():
            print(f"warning: NSE list download failed ({exc}); using stale cache", file=sys.stderr)
            return pd.read_csv(cached)
        raise SystemExit(f"error: could not download {fname} from NSE: {exc}")
    cached.write_text(raw)
    return pd.read_csv(io.StringIO(raw))


def download_closes(tickers: list[str]) -> pd.DataFrame:
    data = yf.download(
        tickers, period="15mo", interval="1d", auto_adjust=True,
        progress=False, threads=True, group_by="column",
    )
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]
    return closes.dropna(how="all")


def index_trend_score(nifty: pd.Series) -> tuple[float, dict]:
    last = float(nifty.iloc[-1])
    dma50 = float(nifty.rolling(50).mean().iloc[-1])
    dma200 = float(nifty.rolling(200).mean().iloc[-1])
    above50, above200 = last > dma50, last > dma200
    score = {(True, True): 100, (False, True): 60, (True, False): 40, (False, False): 0}[(above50, above200)]
    return score, {
        "close": round(last, 2), "dma50": round(dma50, 2), "dma200": round(dma200, 2),
        "above_50dma": above50, "above_200dma": above200,
        "pct_from_200dma": round((last / dma200 - 1) * 100, 2),
    }


def vix_score(vix: float) -> float:
    if vix < 12:
        return 100
    if vix < 16:
        return 75
    if vix < 20:
        return 45
    if vix < 25:
        return 20
    return 0


def analyze(universe: str) -> dict:
    cons = load_constituents(universe)
    cons["Ticker"] = cons["Symbol"].str.strip() + ".NS"
    tickers = cons["Ticker"].tolist()

    print(f"Downloading {len(tickers)} {universe} stocks + Nifty 50 + India VIX ...", file=sys.stderr)
    closes = download_closes(tickers + [NIFTY, VIX])
    nifty = closes.pop(NIFTY).dropna()
    vix_series = closes.pop(VIX).dropna()
    stocks = closes[[t for t in tickers if t in closes.columns]]

    # Need >= 200 sessions for the 200-DMA; recent listings are excluded from DMA stats.
    valid = [c for c in stocks.columns if stocks[c].dropna().shape[0] >= 200 and pd.notna(stocks[c].iloc[-1])]
    missing = sorted(set(tickers) - set(valid))
    px = stocks[valid].ffill()

    dma20, dma50, dma200 = px.rolling(20).mean(), px.rolling(50).mean(), px.rolling(200).mean()
    above20_hist = (px > dma20).mean(axis=1) * 100
    above50_hist = (px > dma50).mean(axis=1) * 100
    above200_hist = (px > dma200).mean(axis=1) * 100

    last = px.iloc[-1]
    hi52 = px.iloc[-252:].max()
    lo52 = px.iloc[-252:].min()
    new_highs = int((last >= hi52 * 0.999).sum())
    new_lows = int((last <= lo52 * 1.001).sum())
    near_highs = int((last >= hi52 * 0.95).sum())

    chg1d = px.iloc[-1] / px.iloc[-2] - 1
    advances, declines = int((chg1d > 0).sum()), int((chg1d < 0).sum())

    pct200, pct50, pct20 = float(above200_hist.iloc[-1]), float(above50_hist.iloc[-1]), float(above20_hist.iloc[-1])
    momentum = pct50 - float(above50_hist.iloc[-11])
    nh_nl = 50.0 if new_highs + new_lows == 0 else new_highs / (new_highs + new_lows) * 100
    idx_score, idx_info = index_trend_score(nifty)
    vix_now = float(vix_series.iloc[-1])

    components = {
        "pct_above_200dma": {"value": round(pct200, 1), "score": round(pct200, 1)},
        "pct_above_50dma": {"value": round(pct50, 1), "score": round(pct50, 1)},
        "breadth_momentum": {"value": round(momentum, 1), "score": round(clamp(50 + momentum * 2.5), 1),
                             "note": "10-session change in % above 50-DMA (pts)"},
        "new_highs_lows": {"value": f"{new_highs} NH / {new_lows} NL", "score": round(nh_nl, 1)},
        "index_trend": {"value": idx_info, "score": idx_score},
        "india_vix": {"value": round(vix_now, 2), "score": vix_score(vix_now)},
    }
    composite = sum(components[k]["score"] * w for k, w in WEIGHTS.items()) / sum(WEIGHTS.values())
    zone = next(z for z in ZONES if composite >= z[0])

    # Sector breadth: % above 50-DMA and median 1-month return per NSE industry.
    ret1m = px.iloc[-1] / px.iloc[-22] - 1
    above50_now = px.iloc[-1] > dma50.iloc[-1]
    industry = cons.set_index("Ticker")["Industry"]
    sec = pd.DataFrame({"industry": industry.reindex(valid), "above50": above50_now, "ret1m": ret1m})
    sectors = (
        sec.groupby("industry")
        .agg(stocks=("above50", "size"), pct_above_50dma=("above50", "mean"), median_1m_return=("ret1m", "median"))
        .assign(pct_above_50dma=lambda d: (d.pct_above_50dma * 100).round(1),
                median_1m_return=lambda d: (d.median_1m_return * 100).round(2))
        .query("stocks >= 3")
        .sort_values("pct_above_50dma", ascending=False)
    )

    history = pd.DataFrame({
        "pct_above_20dma": above20_hist, "pct_above_50dma": above50_hist, "pct_above_200dma": above200_hist,
    }).iloc[-30:].round(1)
    history.index = history.index.strftime("%Y-%m-%d")

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": px.index[-1].strftime("%Y-%m-%d"),
        "universe": universe,
        "stocks_analyzed": len(valid),
        "stocks_excluded": len(missing),
        "composite_score": round(composite, 1),
        "zone": zone[1],
        "suggested_equity_exposure": zone[2],
        "guidance": zone[3],
        "components": components,
        "breadth": {
            "pct_above_20dma": round(pct20, 1), "pct_above_50dma": round(pct50, 1),
            "pct_above_200dma": round(pct200, 1),
            "advances": advances, "declines": declines,
            "new_52w_highs": new_highs, "new_52w_lows": new_lows, "within_5pct_of_52w_high": near_highs,
        },
        "sectors": sectors.reset_index().to_dict(orient="records"),
        "history_30d": history.reset_index(names="date").to_dict(orient="records"),
        "excluded_tickers": missing,
        "caveats": [
            "Uses CURRENT index constituents (survivorship bias in history).",
            "Yahoo Finance EOD data; may lag NSE by a session or contain gaps.",
            "Stocks with < 200 sessions of history are excluded.",
        ],
    }


def to_markdown(r: dict) -> str:
    b, c = r["breadth"], r["components"]
    idx = c["index_trend"]["value"]
    lines = [
        f"# NSE Breadth Report — {r['universe'].upper()} — {r['as_of']}",
        "",
        f"**Composite score: {r['composite_score']} / 100 — {r['zone']}**  ",
        f"Suggested equity/swing exposure: **{r['suggested_equity_exposure']}**  ",
        f"{r['guidance']}",
        "",
        "## Components",
        "| Component | Value | Score | Weight |",
        "|---|---|---|---|",
    ]
    for k, w in WEIGHTS.items():
        v = c[k]["value"]
        if k == "index_trend":
            v = f"Nifty {idx['close']} ({idx['pct_from_200dma']:+}% vs 200-DMA)"
        lines.append(f"| {k} | {v} | {c[k]['score']} | {w} |")
    lines += [
        "",
        "## Breadth snapshot",
        f"- Above 20 / 50 / 200-DMA: {b['pct_above_20dma']}% / {b['pct_above_50dma']}% / {b['pct_above_200dma']}%",
        f"- Advances / Declines (last session): {b['advances']} / {b['declines']}",
        f"- 52-week highs / lows: {b['new_52w_highs']} / {b['new_52w_lows']} "
        f"(within 5% of high: {b['within_5pct_of_52w_high']})",
        f"- Stocks analyzed: {r['stocks_analyzed']} (excluded: {r['stocks_excluded']})",
        "",
        "## Sector breadth (strongest → weakest)",
        "| Industry | Stocks | % > 50-DMA | Median 1M return % |",
        "|---|---|---|---|",
    ]
    for s in r["sectors"]:
        lines.append(f"| {s['industry']} | {s['stocks']} | {s['pct_above_50dma']} | {s['median_1m_return']} |")
    lines += ["", "## Last 10 sessions (% above DMA)", "| Date | 20-DMA | 50-DMA | 200-DMA |", "|---|---|---|---|"]
    for h in r["history_30d"][-10:]:
        lines.append(f"| {h['date']} | {h['pct_above_20dma']} | {h['pct_above_50dma']} | {h['pct_above_200dma']} |")
    lines += ["", "## Caveats"] + [f"- {x}" for x in r["caveats"]]
    lines += ["", "_Educational/process tool, not investment advice._"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score NSE market breadth (0-100).")
    ap.add_argument("--universe", choices=sorted(UNIVERSES), default="nifty500")
    ap.add_argument("--output-dir", default="reports/data")
    args = ap.parse_args()

    result = analyze(args.universe)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"nse_breadth_{args.universe}_{result['as_of']}"
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str))
    (out / f"{stem}.md").write_text(to_markdown(result))

    print(f"JSON report: {out / (stem + '.json')}")
    print(f"Markdown report: {out / (stem + '.md')}")
    print(f"\n{result['universe'].upper()} as of {result['as_of']}: "
          f"score {result['composite_score']} ({result['zone']}) — exposure {result['suggested_equity_exposure']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
