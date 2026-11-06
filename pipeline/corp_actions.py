# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Price-adjusting corporate actions (demerger, split, bonus, rights, consolidation) from NSE.

On the ex-date these change the share price for a mechanical reason, so a chart can show a "crash" that is
not a loss. Ordinary dividends are left out. Covers the last 90 days and the next 45 days.

Usage:
  uv run pipeline/corp_actions.py --out data/2026-11-04/corp_actions.json
"""

from __future__ import annotations

import argparse
import io
import csv
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
API = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={a}&to_date={b}"
N500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

# Order matters: a "Scheme Of Arrangement - Bonus" is a bonus, a plain "Scheme Of Arrangement" a restructuring.
KINDS = [
    ("demerger", r"demerg"),
    ("split", r"split|sub-?division"),
    ("consolidation", r"consolidat"),
    ("bonus", r"bonus"),
    ("rights", r"\brights\b"),
    ("capital reduction", r"capital reduction|reduction of capital"),
    ("restructuring", r"scheme of arrangement|amalgamation|merger"),
]
EFFECT = {
    "demerger": "Price drops by roughly the value of the business moved to the new company; holders get shares of that company.",
    "split": "Price is divided by the split ratio; you hold proportionally more shares. No change in value.",
    "consolidation": "Opposite of a split: price is multiplied, you hold fewer shares. No change in value.",
    "bonus": "Free extra shares; price adjusts down in proportion. No change in value.",
    "rights": "New shares offered at a set price; the market price adjusts slightly if that price is below market.",
    "capital reduction": "Share count and price change under a court-approved scheme; check the terms.",
    "restructuring": "Merger or scheme of arrangement; price and holdings can change, check the scheme terms.",
}


def get(url: str, referer: str = "https://www.nseindia.com/") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    for attempt in range(3):  # NSE's API is sometimes slow in the evening
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except (TimeoutError, OSError) as exc:
            if attempt == 2:
                raise
            print(f"retrying after: {exc}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))


def ratio_note(kind: str, subject: str) -> str:
    """Turn the NSE subject into a concrete price effect where the ratio is in the text."""
    s = subject.replace(",", "")
    if kind == "split":
        m = re.search(r"Rs\.?\s*([\d.]+).*?(?:Rs|Re)\.?\s*([\d.]+)", s)
        if m and float(m.group(2)):
            n = float(m.group(1)) / float(m.group(2))
            return f"1 share becomes {n:g}; price ÷ {n:g}"
    if kind == "bonus":
        m = re.search(r"(\d+)\s*:\s*(\d+)", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return f"{a} free for every {b} held; price × {b}/{a + b} ≈ −{100 * a / (a + b):.0f}%"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE price-adjusting corporate actions.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--past-days", type=int, default=90)
    ap.add_argument("--ahead-days", type=int, default=45)
    args = ap.parse_args()

    today = date.today()
    a, b = today - timedelta(days=args.past_days), today + timedelta(days=args.ahead_days)
    rows = json.loads(get(API.format(a=a.strftime("%d-%m-%Y"), b=b.strftime("%d-%m-%Y")),
                          "https://www.nseindia.com/companies-listing/corporate-filings-actions"))
    try:
        n500 = {r["Symbol"].strip() for r in csv.DictReader(io.StringIO(get(N500_URL).decode()))}
    except Exception:
        n500 = set()

    seen, actions = set(), []
    for r in rows:
        subject = (r.get("subject") or "").strip()
        kind = next((k for k, rx in KINDS if re.search(rx, subject, re.I)), None)
        if not kind or (r.get("series") or "EQ") != "EQ":
            continue
        try:
            ex = datetime.strptime(r["exDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        key = (r["symbol"], kind, ex)
        if key in seen:  # NSE lists one row per instrument in some schemes
            continue
        seen.add(key)
        actions.append({
            "symbol": r["symbol"], "company": r.get("comp", ""), "kind": kind, "subject": subject,
            "ex_date": ex.isoformat(), "upcoming": ex >= today, "nifty500": r["symbol"] in n500,
            "effect": ratio_note(kind, subject) or EFFECT[kind],
        })
    actions.sort(key=lambda x: x["ex_date"])
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "from": a.isoformat(), "to": b.isoformat(),
           "effects": EFFECT, "actions": actions}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    up = sum(x["upcoming"] for x in actions)
    print(f"wrote {args.out}: {len(actions)} actions ({up} upcoming, {sum(x['nifty500'] for x in actions)} in Nifty 500)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
