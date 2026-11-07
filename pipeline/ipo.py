# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""IPO watch from NSE's public pages: open now, coming soon, and recently listed main-board IPOs.

For each IPO it records plain facts a learner can judge for themselves — price band, lot size, how many times
each investor group subscribed, whether the money goes to the company (fresh issue) or to existing owners
(offer for sale) — and, for recent listings, the listing-day and latest price against the issue price.
It never labels an IPO good or bad. SME IPOs are kept but marked, and the site hides them by default.

Usage:
  uv run pipeline/ipo.py --out data/weekend/2026-11-07/ipo.json [--recent-days 30]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
NSE = "https://www.nseindia.com/api/"
REFERER = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"
BHAV = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"


def get(url: str, referer: str = REFERER) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, OSError) as exc:
            if attempt == 2:
                raise
            print(f"retrying after: {exc}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    return b""


def nse(path: str):
    return json.loads(get(NSE + path) or b"null")


def pick(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "-"):
            return str(v).strip()
    return ""


def parse_date(s: str) -> date | None:
    for f in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), f).date()  # month names match in any case
        except ValueError:
            continue
    return None


def num(s: str) -> float | None:
    m = re.search(r"[\d,]+(?:\.\d+)?", s or "")
    try:
        return float(m.group().replace(",", "")) if m else None
    except ValueError:
        return None


def band(text: str) -> str:
    """'Rs. 78/- to Rs. 82/- per equity share' → '₹78–82'."""
    nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
    return "₹" + "–".join(n.replace(",", "") for n in nums[:2]) if nums else ""


def base(row: dict, status: str) -> dict:
    """One IPO from any of NSE's three lists, whose field names differ."""
    kind = pick(row, "series", "securityType", "issueType").upper()
    start = parse_date(pick(row, "issueStartDate", "ipoStartDate"))
    end = parse_date(pick(row, "issueEndDate", "ipoEndDate"))
    listing = parse_date(pick(row, "listingDate"))
    price = pick(row, "priceRange", "priceBand")
    return {
        "symbol": pick(row, "symbol"),
        "company": pick(row, "companyName", "company"),
        "sme": "SME" in kind or kind in ("ST", "SM"),
        "status": status,
        "open": start.isoformat() if start else None,
        "close": end.isoformat() if end else None,
        "listing": listing.isoformat() if listing else None,
        "price_band": band(price),
        "issue_price": num(pick(row, "issuePrice")) if status == "listed" else None,
        "issue_size": pick(row, "issueSize"),
        "times_subscribed": num(pick(row, "noOfTime")),
    }


def detail(symbol: str) -> dict:
    """Subscription by investor group and the issue structure, from the IPO's own NSE page."""
    try:
        d = nse(f"ipo-detail?symbol={symbol}&series=EQ") or {}
    except Exception as exc:
        return {"detail_error": str(exc)[:120]}
    out: dict = {}
    info = {(x.get("title") or "").strip(): (x.get("value") or "").strip('" ') for x in (d.get("issueInfo") or {}).get("dataList", [])}
    size = info.get("Issue Size", "").lower()
    fresh, ofs = "fresh issue" in size, "offer for sale" in size
    out["structure"] = ("fresh + OFS" if fresh and ofs else "fresh issue only" if fresh else "OFS only" if ofs else "")
    lot = num(info.get("Bid Lot", ""))
    out["lot"] = int(lot) if lot else None
    if info.get("Price Range"):
        out["price_band"] = band(info["Price Range"])
    out["industry"] = ((d.get("metaInfo") or {}).get("industry") or "").strip()
    rhp = info.get("Red Herring Prospectus", "")
    out["rhp"] = rhp if rhp.startswith("https://") else ""

    act = d.get("activeCat") or {}
    groups = {"qib": r"qualified institutional", "nii": r"^non institutional investors$", "retail": r"retail individual",
              "total": r"^total$"}
    sub = {}
    for r in act.get("dataList", []):
        cat = (r.get("category") or "").strip().lower()
        for key, rx in groups.items():
            if key not in sub and re.search(rx, cat):
                x = num(r.get("noOfTotalMeant") or "")
                if x is not None:
                    sub[key] = round(x, 2)
    if "total" not in sub:  # the active table sometimes lacks a total row; the bid table has one
        for r in d.get("bidDetails") or []:
            if (r.get("category") or "").strip().lower() == "total" and num(r.get("noOfTime") or "") is not None:
                sub["total"] = round(num(r["noOfTime"]), 2)
    if any(sub.values()):  # NSE shows all-zero tables when it has no figures; that is "unknown", not "0×"
        out["subscription"] = sub
        m = re.search(r"as on (.+)$", act.get("updateTime") or "")
        out["subscription_as_of"] = m.group(1).strip() if m and "null" not in m.group(1) else ""
    return out


def bhavcopy(d: date) -> dict[str, dict] | None:
    try:
        text = get(BHAV.format(d=d), "https://www.nseindia.com/").decode()
    except urllib.error.HTTPError:
        return None
    rows = {}
    for r in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("SERIES") in ("EQ", "BE") and (r["SYMBOL"] not in rows or r["SERIES"] == "EQ"):
            rows[r["SYMBOL"]] = r
    return rows


def latest_bhavcopy(today: date) -> tuple[date, dict] | tuple[None, dict]:
    d = today
    for _ in range(8):
        if d.weekday() < 5:
            rows = bhavcopy(d)
            if rows:
                return d, rows
        d -= timedelta(days=1)
    return None, {}


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE IPO watch.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--recent-days", type=int, default=30)
    args = ap.parse_args()
    today = date.today()
    errors: dict[str, str] = {}

    ipos: list[dict] = []
    for path, status in (("ipo-current-issue", "open"), ("all-upcoming-issues?category=ipo", "upcoming")):
        try:
            rows = nse(path) or []
            rows = rows.get("data", []) if isinstance(rows, dict) else rows
            ipos += [base(r, status) for r in rows if isinstance(r, dict)]
        except Exception as exc:
            errors[status] = str(exc)[:200]
    try:
        cutoff = today - timedelta(days=args.recent_days)
        for r in nse("public-past-issues") or []:
            x = base(r, "listed")
            # Skip bonds and re-listings: their "IPO" opened months or years before the listing date.
            fresh = x["open"] and date.fromisoformat(x["listing"] or "1900-01-01") - date.fromisoformat(x["open"]) <= timedelta(days=21)
            if x["listing"] and fresh and cutoff <= date.fromisoformat(x["listing"]) <= today:
                ipos.append(x)
    except Exception as exc:
        errors["listed"] = str(exc)[:200]

    # An IPO can sit in "upcoming" and "open" at once around its start date; keep the most advanced status.
    rank = {"listed": 0, "open": 1, "upcoming": 2}
    seen, unique = set(), []
    for x in sorted(ipos, key=lambda x: rank[x["status"]]):
        if x["symbol"] and x["symbol"] not in seen:
            seen.add(x["symbol"])
            unique.append(x)
    ipos = unique

    for x in ipos:
        if x["sme"]:
            continue  # the site hides SME issues by default; skip their detail calls to stay light on NSE
        for k, v in detail(x["symbol"]).items():
            if v or k not in x:
                x[k] = v
        time.sleep(0.4)

    listed = [x for x in ipos if x["status"] == "listed" and not x["sme"]]
    if listed:
        last_day, last = latest_bhavcopy(today)
        by_day: dict[str, dict] = {}
        for x in listed:
            if x["listing"] not in by_day:
                by_day[x["listing"]] = bhavcopy(date.fromisoformat(x["listing"])) or {}
            first = by_day[x["listing"]].get(x["symbol"])
            now = last.get(x["symbol"])
            ip = x.get("issue_price")
            if first and ip:
                x["listing_open"] = float(first["OPEN_PRICE"])
                x["listing_close"] = float(first["CLOSE_PRICE"])
                x["listing_gain_pct"] = round(100 * (x["listing_open"] / ip - 1), 1)
            if now and ip:
                x["last_close"] = float(now["CLOSE_PRICE"])
                x["last_close_date"] = last_day.isoformat()
                x["since_issue_pct"] = round(100 * (x["last_close"] / ip - 1), 1)

    order = {"open": 0, "upcoming": 1, "listed": 2}
    ipos.sort(key=lambda x: x["open"] or "")              # open and upcoming: soonest first
    live = [x for x in ipos if x["status"] != "listed"]
    done = sorted((x for x in ipos if x["status"] == "listed"), key=lambda x: x["listing"], reverse=True)
    ipos = sorted(live, key=lambda x: order[x["status"]]) + done
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "recent_days": args.recent_days,
           "errors": errors, "ipos": ipos}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    counts = {s: sum(1 for x in ipos if x["status"] == s and not x["sme"]) for s in order}
    print(f"wrote {args.out}: main-board {counts['open']} open, {counts['upcoming']} upcoming, "
          f"{counts['listed']} listed in {args.recent_days}d" + (f"; errors: {', '.join(errors)}" if errors else ""))
    return 1 if len(errors) == 3 else 0


if __name__ == "__main__":
    sys.exit(main())
