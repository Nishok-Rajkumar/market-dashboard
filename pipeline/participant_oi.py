# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Participant-wise F&O open interest (FII, DII, Pro, Client) from NSE archives.

The headline number is FII positioning in index futures: what share of their index-futures contracts are
long. NSE publishes one CSV per session; history is kept in state/participant_oi.csv and missing sessions
from the last ~45 days are backfilled on each run.

Usage:
  uv run pipeline/participant_oi.py --state state --out data/2026-11-02/participant_oi.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
URL = "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv"
COLS = {  # NSE header → our short name
    "Future Index Long": "fut_idx_long", "Future Index Short": "fut_idx_short",
    "Future Stock Long": "fut_stk_long", "Future Stock Short": "fut_stk_short",
    "Option Index Call Long": "idx_call_long", "Option Index Put Long": "idx_put_long",
    "Option Index Call Short": "idx_call_short", "Option Index Put Short": "idx_put_short",
    "Total Long Contracts": "total_long", "Total Short Contracts": "total_short",
}
FIELDS = ["date", "client"] + list(COLS.values())


def fetch(d: date) -> list[dict] | None:
    req = urllib.request.Request(URL.format(d=d.strftime("%d%m%Y")), headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return None  # holiday or not yet published
    lines = text.strip().splitlines()[1:]  # first line is a title
    rows = []
    for rec in csv.DictReader(io.StringIO("\n".join(lines))):
        rec = {k.strip(): (v or "").strip() for k, v in rec.items() if k}
        if rec.get("Client Type") in ("Client", "DII", "FII", "Pro"):
            rows.append({"date": d.isoformat(), "client": rec["Client Type"],
                         **{short: int(float(rec[long])) for long, short in COLS.items()}})
    return rows or None


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as fh:
        return [{k: (v if k in ("date", "client") else int(v)) for k, v in r.items()} for r in csv.DictReader(fh)]


def long_pct(r: dict, long: str, short: str) -> float:
    tot = r[long] + r[short]
    return round(100 * r[long] / tot, 1) if tot else 0.0


def read_fii(pct: float) -> str:
    if pct < 20:
        return ("Extremely bearish — FIIs hold very few longs in index futures. Traders watch extremes like this as a "
                "contrarian sign (short covering can lift the index), but they can last for weeks.")
    if pct < 35:
        return "Bearish — FIIs are mostly short index futures."
    if pct < 50:
        return "Mildly bearish — slightly more shorts than longs."
    if pct < 65:
        return "Mildly bullish — slightly more longs than shorts."
    return "Bullish — FIIs are mostly long index futures."


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE participant-wise open interest.")
    ap.add_argument("--state", default="state")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lookback-days", type=int, default=45)
    args = ap.parse_args()

    hist_path = Path(args.state) / "participant_oi.csv"
    hist = load_history(hist_path)
    have = {r["date"] for r in hist}
    today = date.today()
    for i in range(args.lookback_days, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5 or d.isoformat() in have:
            continue
        rows = fetch(d)
        if rows:
            hist += rows
    if not hist:
        print("error: no participant OI data", file=sys.stderr)
        return 1
    hist.sort(key=lambda r: (r["date"], r["client"]))
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    with hist_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(hist)

    dates = sorted({r["date"] for r in hist})
    latest = dates[-1]
    by = {(r["date"], r["client"]): r for r in hist}
    clients = {}
    for c in ("FII", "DII", "Pro", "Client"):
        r = by[(latest, c)]
        prev = by.get((dates[-2], c)) if len(dates) > 1 else None
        clients[c] = {
            "fut_idx_long": r["fut_idx_long"], "fut_idx_short": r["fut_idx_short"],
            "fut_idx_net": r["fut_idx_long"] - r["fut_idx_short"],
            "fut_idx_long_pct": long_pct(r, "fut_idx_long", "fut_idx_short"),
            "fut_idx_net_chg": (r["fut_idx_long"] - r["fut_idx_short"]) - (prev["fut_idx_long"] - prev["fut_idx_short"]) if prev else None,
            "idx_call_net": r["idx_call_long"] - r["idx_call_short"],
            "idx_put_net": r["idx_put_long"] - r["idx_put_short"],
            "fut_stk_long_pct": long_pct(r, "fut_stk_long", "fut_stk_short"),
        }
    fii_series = [{"date": d, "fut_idx_long_pct": long_pct(by[(d, "FII")], "fut_idx_long", "fut_idx_short"),
                   "fut_idx_net": by[(d, "FII")]["fut_idx_long"] - by[(d, "FII")]["fut_idx_short"]}
                  for d in dates if (d, "FII") in by][-60:]
    pcts = [x["fut_idx_long_pct"] for x in fii_series]
    now = clients["FII"]["fut_idx_long_pct"]
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"), "as_of": latest,
        "clients": clients, "fii_history": fii_series,
        "fii_read": read_fii(now),
        "fii_pct_rank": round(100 * sum(p <= now for p in pcts) / len(pcts)),  # percentile within the history shown
        "sessions": len(fii_series),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: FII index futures {now}% long as of {latest} ({len(fii_series)} sessions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
