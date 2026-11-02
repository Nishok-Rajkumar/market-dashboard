# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""NSE Sector Rotation.

Relative-rotation analysis of NSE sectoral/thematic indices against the Nifty 500
(RRG-style). For each index:

  RS        = index / benchmark
  RS-Ratio  = 100 * RS / SMA(RS, 50)           (> 100: outperforming its own trend)
  RS-Mom    = 100 * RS-Ratio / RS-Ratio[10]    (> 100: relative strength accelerating)

Quadrants: LEADING (ratio>100, mom>100), WEAKENING (ratio>100, mom<100),
LAGGING (ratio<100, mom<100), IMPROVING (ratio<100, mom>100).
Typical rotation is clockwise: Improving -> Leading -> Weakening -> Lagging.

Usage:
  uv run scripts/nse_sector_rotation.py [--output-dir reports]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

BENCHMARK = ("^CRSLDX", "Nifty 500")
# label -> (Yahoo ticker or None, NSE index name). Yahoo is tried first; NSE's
# historical API fills in indices Yahoo has no history for.
SECTORS = {
    "Bank": ("^NSEBANK", "NIFTY BANK"),
    "Private Bank": (None, "NIFTY PRIVATE BANK"),
    "PSU Bank": ("^CNXPSUBANK", "NIFTY PSU BANK"),
    "Financial Services": ("NIFTY_FIN_SERVICE.NS", "NIFTY FINANCIAL SERVICES"),
    "Capital Markets": (None, "NIFTY CAPITAL MARKETS"),
    "IT": ("^CNXIT", "NIFTY IT"),
    "Auto": ("^CNXAUTO", "NIFTY AUTO"),
    "EV & New Age Auto": (None, "NIFTY EV & NEW AGE AUTOMOTIVE"),
    "FMCG": ("^CNXFMCG", "NIFTY FMCG"),
    "Pharma": ("^CNXPHARMA", "NIFTY PHARMA"),
    "Healthcare": (None, "NIFTY HEALTHCARE INDEX"),
    "Metal": ("^CNXMETAL", "NIFTY METAL"),
    "Realty": ("^CNXREALTY", "NIFTY REALTY"),
    "Energy": ("^CNXENERGY", "NIFTY ENERGY"),
    "Oil & Gas": (None, "NIFTY OIL & GAS"),
    "Infrastructure": ("^CNXINFRA", "NIFTY INFRASTRUCTURE"),
    "Defence": (None, "NIFTY INDIA DEFENCE"),
    "Manufacturing": (None, "NIFTY INDIA MANUFACTURING"),
    "Media": (None, "NIFTY MEDIA"),
    "Consumer Durables": (None, "NIFTY CONSUMER DURABLES"),
    "Consumption": ("^CNXCONSUM", "NIFTY INDIA CONSUMPTION"),
    "Chemicals": (None, "NIFTY CHEMICALS"),
    "PSE (PSU stocks)": ("^CNXPSE", "NIFTY PSE"),
    "Commodities": (None, "NIFTY COMMODITIES"),
    "MNC": ("^CNXMNC", "NIFTY MNC"),
    "Midcap 100": (None, "NIFTY MIDCAP 100"),
    "Smallcap 100": (None, "NIFTY SMALLCAP 100"),
}
NSE_HIST = "https://www.nseindia.com/api/historicalOR/indicesHistory?indexType={name}&from={start}&to={end}"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/reports-indices-historical-index-data",
    "Accept": "application/json",
}
CACHE_DIR = Path.home() / ".cache" / "nse-skills" / "index-history"


def nse_index_history(name: str, days: int = 730) -> pd.Series:
    """Daily closes from NSE (API returns <= 70 rows per call, so fetch 85-day chunks). Cached per day."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{name.replace(' ', '_').replace('&', 'and')}.csv"
    if cache.exists() and date.fromtimestamp(cache.stat().st_mtime) == date.today():
        return pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
    points: dict[pd.Timestamp, float] = {}
    end = date.today()
    start = end - timedelta(days=days)
    while start <= end:
        chunk_end = min(start + timedelta(days=85), end)
        url = NSE_HIST.format(name=urllib.parse.quote(name), start=start.strftime("%d-%m-%Y"),
                              end=chunk_end.strftime("%d-%m-%Y"))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=NSE_HEADERS), timeout=30) as resp:
                for row in json.loads(resp.read())["data"]:
                    points[pd.Timestamp(datetime.strptime(row["EOD_TIMESTAMP"], "%d-%b-%Y"))] = float(row["EOD_CLOSE_INDEX_VAL"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"warning: NSE history chunk failed for {name}: {exc}", file=sys.stderr)
        start = chunk_end + timedelta(days=1)
        time.sleep(0.3)
    series = pd.Series(points, name=name).sort_index()
    if len(series):
        series.to_frame().to_csv(cache)
    return series


def quadrant(ratio: float, mom: float) -> str:
    if ratio >= 100:
        return "LEADING" if mom >= 100 else "WEAKENING"
    return "IMPROVING" if mom >= 100 else "LAGGING"


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE sector relative rotation.")
    ap.add_argument("--output-dir", default="reports/data")
    args = ap.parse_args()

    tickers = [BENCHMARK[0]] + [y for y, _ in SECTORS.values() if y]
    print(f"Downloading {len(SECTORS) + 1} NSE indices (Yahoo, NSE fallback) ...", file=sys.stderr)
    yahoo = yf.download(tickers, period="2y", interval="1d", auto_adjust=True, progress=False)["Close"]
    bench = yahoo[BENCHMARK[0]].dropna()
    series = {}
    for name, (yt, nse_name) in SECTORS.items():
        s = yahoo[yt].dropna() if yt and yt in yahoo else pd.Series(dtype=float)
        if len(s) < 260:
            s = nse_index_history(nse_name)
        series[name] = s
    closes = pd.DataFrame(series).reindex(bench.index).ffill()

    rows = []
    for name, (yt, nse_name) in SECTORS.items():
        t = yt or nse_name
        if closes[name].dropna().shape[0] < 260:
            print(f"warning: insufficient data for {name}", file=sys.stderr)
            continue
        px = closes[name]
        rs = px / bench
        ratio = 100 * rs / rs.rolling(50).mean()
        mom = 100 * ratio / ratio.shift(10)
        r_now, m_now = float(ratio.iloc[-1]), float(mom.iloc[-1])
        # Weekly trail (last 5 Fridays-ish: every 5 sessions) to show direction of travel.
        trail = [quadrant(float(ratio.iloc[-1 - 5 * k]), float(mom.iloc[-1 - 5 * k])) for k in range(4, -1, -1)]

        def ret(n: int) -> float:
            return round((float(px.iloc[-1]) / float(px.iloc[-1 - n]) - 1) * 100, 2)

        rows.append({
            "sector": name, "ticker": t, "close": round(float(px.iloc[-1]), 2),
            "rs_ratio": round(r_now, 2), "rs_momentum": round(m_now, 2), "quadrant": quadrant(r_now, m_now),
            "trail_5w": trail,
            "ret_1w": ret(5), "ret_1m": ret(21), "ret_3m": ret(63), "ret_6m": ret(126), "ret_1y": ret(252),
            "rel_3m_vs_nifty500": round(ret(63) - (float(bench.iloc[-1]) / float(bench.iloc[-64]) - 1) * 100, 2),
            "above_50dma": bool(px.iloc[-1] > px.rolling(50).mean().iloc[-1]),
            "above_200dma": bool(px.iloc[-1] > px.rolling(200).mean().iloc[-1]),
        })

    order = {"LEADING": 0, "IMPROVING": 1, "WEAKENING": 2, "LAGGING": 3}
    rows.sort(key=lambda r: (order[r["quadrant"]], -r["rs_ratio"]))
    as_of = bench.index[-1].strftime("%Y-%m-%d")
    b1m = round((float(bench.iloc[-1]) / float(bench.iloc[-22]) - 1) * 100, 2)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"nse_sector_rotation_{as_of}"
    (out / f"{stem}.json").write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"), "as_of": as_of,
        "benchmark": BENCHMARK[1], "benchmark_ret_1m": b1m, "sectors": rows}, indent=2))

    md = [f"# NSE Sector Rotation vs {BENCHMARK[1]} — {as_of}", "",
          f"Nifty 500 1-month return: {b1m}%", ""]
    for q in ("LEADING", "IMPROVING", "WEAKENING", "LAGGING"):
        items = [r for r in rows if r["quadrant"] == q]
        md.append(f"**{q}:** " + (", ".join(r["sector"] for r in items) or "—"))
    md += ["", "| Sector | Quadrant | RS-Ratio | RS-Mom | 1W % | 1M % | 3M % | 6M % | 1Y % | 3M vs N500 | >50DMA | >200DMA | 5-week trail |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        trail = " → ".join(q[:3] for q in r["trail_5w"])
        md.append(f"| {r['sector']} | {r['quadrant']} | {r['rs_ratio']} | {r['rs_momentum']} | {r['ret_1w']} | {r['ret_1m']} "
                  f"| {r['ret_3m']} | {r['ret_6m']} | {r['ret_1y']} | {r['rel_3m_vs_nifty500']} "
                  f"| {'Y' if r['above_50dma'] else 'N'} | {'Y' if r['above_200dma'] else 'N'} | {trail} |")
    md += ["", "_RRG-style approximation (not the proprietary JdK formula). Process tool, not investment advice._"]
    (out / f"{stem}.md").write_text("\n".join(md) + "\n")

    print(f"JSON report: {out / (stem + '.json')}")
    print(f"Markdown report: {out / (stem + '.md')}")
    for q in ("LEADING", "IMPROVING", "WEAKENING", "LAGGING"):
        print(f"{q:10s}: " + ", ".join(r["sector"] for r in rows if r["quadrant"] == q))
    return 0


if __name__ == "__main__":
    sys.exit(main())
