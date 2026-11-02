# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check which data sources answer from the machine this runs on (e.g. a GitHub Actions server).

NSE often blocks servers outside India; run this from GitHub Actions to see which sections will work.
Usage:
  uv run pipeline/check_sources.py
"""

from __future__ import annotations

import sys
import urllib.request
from datetime import date, timedelta

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

d = date.today() - timedelta(days=1)
while d.weekday() >= 5:
    d -= timedelta(days=1)

SOURCES = {
    "NSE archives: Nifty 500 list (breadth, swing)": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "NSE archives: F&O ban list": "https://archives.nseindia.com/content/fo/fo_secban.csv",
    "NSE archives: bhavcopy (delivery, movers)": f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv",
    "NSE API: FII/DII": "https://www.nseindia.com/api/fiidiiTradeReact",
    "NSE API: option chain": "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
    "NSE API: event calendar": "https://www.nseindia.com/api/event-calendar",
    "Yahoo Finance": "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d",
    "Groq API": "https://api.groq.com/openai/v1/models",
    "RSS: Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
}


def main() -> int:
    for name, url in SOURCES.items():
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/", "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                print(f"OK    {r.status}  {len(r.read()):>9,} bytes  {name}")
        except Exception as exc:
            print(f"FAIL  {str(exc)[:60]:<60}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
