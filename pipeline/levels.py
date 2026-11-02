# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""Classic floor pivots, 52-week range and 50/200-DMA for Nifty 50 and Bank Nifty (Yahoo Finance daily bars).

Usage:
  uv run pipeline/levels.py --out data/2026-11-02/levels.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yfinance as yf

TICKERS = {"^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty"}


def levels(ticker: str) -> dict:
    d = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False).dropna()
    if len(d) < 2:
        raise RuntimeError(f"no data for {ticker}")
    last = d.iloc[-1]
    h, l, c = float(last.High), float(last.Low), float(last.Close)
    p = (h + l + c) / 3
    r = lambda x: round(x, 2)  # noqa: E731
    hi52, lo52 = float(d.High.max()), float(d.Low.min())
    return {
        "date": d.index[-1].strftime("%Y-%m-%d"), "O": r(float(last.Open)), "H": r(h), "L": r(l), "C": r(c),
        "P": r(p), "R1": r(2 * p - l), "R2": r(p + h - l), "R3": r(h + 2 * (p - l)),
        "S1": r(2 * p - h), "S2": r(p - (h - l)), "S3": r(l - 2 * (h - p)),
        "hi52": r(hi52), "lo52": r(lo52),
        "from_high": r((c / hi52 - 1) * 100), "from_low": r((c / lo52 - 1) * 100),
        "dma50": r(float(d.Close.tail(50).mean())), "dma200": r(float(d.Close.tail(200).mean())),
        "chg1d": r((c / float(d.Close.iloc[-2]) - 1) * 100),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Floor pivots for Nifty / Bank Nifty.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = {}
    for t, name in TICKERS.items():
        try:
            result[t] = {"name": name, **levels(t)}
        except Exception as exc:  # one index failing must not drop the other
            print(f"warning: {t} failed: {exc}", file=sys.stderr)
    if not result:
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
