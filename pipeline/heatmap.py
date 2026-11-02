# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""Nifty 50 heatmap data: each stock's day change from the latest NSE bhavcopy, sized by market cap.

Market cap comes from Yahoo Finance; if Yahoo is unavailable, traded value is used for size instead.

Usage:
  uv run pipeline/heatmap.py --out data/2026-11-02/heatmap.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
N50_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
BHAV_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def latest_bhavcopy() -> tuple[date, pd.DataFrame]:
    d = date.today()
    for _ in range(10):
        if d.weekday() < 5:
            try:
                df = pd.read_csv(io.BytesIO(get(BHAV_URL.format(d=d.strftime("%d%m%Y")))), skipinitialspace=True)
                df.columns = [c.strip() for c in df.columns]
                df = df[df["SERIES"].str.strip() == "EQ"].copy()
                df["SYMBOL"] = df["SYMBOL"].str.strip()
                return d, df.set_index("SYMBOL")
            except urllib.error.HTTPError:
                pass
        d -= timedelta(days=1)
    raise RuntimeError("no bhavcopy in the last 10 days")


def market_caps(symbols: list[str]) -> dict[str, float]:
    import yfinance as yf

    def one(s: str) -> tuple[str, float | None]:
        try:
            return s, float(yf.Ticker(f"{s}.NS").fast_info["market_cap"])
        except Exception:
            return s, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return {s: v for s, v in pool.map(one, symbols) if v}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nifty 50 heatmap data.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    n50 = pd.read_csv(io.BytesIO(get(N50_URL)))
    n50["Symbol"] = n50["Symbol"].str.strip()
    day, bhav = latest_bhavcopy()
    caps = market_caps(n50["Symbol"].tolist())
    size_by = "market_cap" if len(caps) >= 40 else "turnover"

    stocks = []
    for _, r in n50.iterrows():
        s = r["Symbol"]
        if s not in bhav.index:
            continue
        b = bhav.loc[s]
        close, prev = float(b["CLOSE_PRICE"]), float(b["PREV_CLOSE"])
        turnover_cr = float(b["TURNOVER_LACS"]) / 100
        stocks.append({
            "symbol": s, "name": r["Company Name"], "industry": r["Industry"],
            "close": round(close, 2), "chg_pct": round((close / prev - 1) * 100, 2),
            "turnover_cr": round(turnover_cr, 1),
            "mcap_cr": round(caps[s] / 1e7) if s in caps else None,
            "size": (caps.get(s, 0) / 1e7 if size_by == "market_cap" else turnover_cr) or turnover_cr,
        })
    out = {"as_of": day.isoformat(), "size_by": size_by, "stocks": stocks}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: {len(stocks)} stocks for {day}, sized by {size_by}")
    return 0 if stocks else 1


if __name__ == "__main__":
    sys.exit(main())
