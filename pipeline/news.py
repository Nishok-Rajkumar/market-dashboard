# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Indian market headlines from free RSS feeds, de-duplicated and tagged by topic.

Usage:
  uv run pipeline/news.py --out data/news.json [--max-age-hours 48]
  uv run pipeline/news.py --out data/weekend/2026-11-07/news.json --weekly   # last 7 days, plus IPO news
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

FEEDS = {
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "ET Stocks": "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms",
    "Livemint": "https://www.livemint.com/rss/markets",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "BusinessLine": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "RBI": "https://www.rbi.org.in/pressreleases_rss.xml",
    "Google News": "https://news.google.com/rss/search?q=Nifty+OR+Sensex+OR+%22stock+market%22&hl=en-IN&gl=IN&ceid=IN:en",
}

# Extra feeds for the weekend digest: Google News searches reach back a whole week, which the publishers'
# own feeds (latest ~50 stories) don't.
WEEKLY_FEEDS = {
    "Google News · week": "https://news.google.com/rss/search?q=Sensex+OR+Nifty+OR+%22Dalal+Street%22+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    "Google News · IPO": "https://news.google.com/rss/search?q=IPO+India+(SEBI+OR+%22price+band%22+OR+DRHP+OR+%22NSE+India%22+OR+BSE)+-Kenya+-Nairobi+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
}

# First matching keywords decide the tags; a headline can carry several.
TAGS = {
    "RBI & rates": r"\brbi\b|repo rate|monetary policy|\bmpc\b|inflation|\bcpi\b|\bwpi\b|rate cut|rate hike",
    "FII/DII flows": r"\bfii|\bfpi|\bdii\b|foreign investor|institutional",
    "Results": r"\bq[1-4]\b|results|earnings|profit|net income|revenue|quarter",
    "Global": r"\bfed\b|wall street|dow|nasdaq|s&p|china|global|us market|treasury|trump|tariff",
    "Crude & commodities": r"crude|brent|oil price|gold|silver|commodit|metal price",
    "Rupee": r"rupee|\binr\b|forex|dollar",
    "Banks": r"\bbank|nbfc|lender|hdfc|icici|\bsbi\b|kotak|axis",
    "IT": r"\bit stocks|\binfosys|\btcs\b|wipro|hcl|tech mahindra|software",
    "Pharma": r"pharma|drug|healthcare|cdmo|\bsun pharma|cipla|dr reddy",
    "Auto": r"\bauto\b|automobile|maruti|tata motors|mahindra|two-wheeler|\bev\b",
    "IPO": r"\bipo\b|listing|grey market|\bgmp\b",
    "Index": r"nifty|sensex|bank nifty|market close|closing bell|opening bell",
}


def fetch(source: str, url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, */*"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    items = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        pub = it.findtext("pubDate")
        try:
            ts = parsedate_to_datetime(pub).astimezone(timezone.utc) if pub else None
        except (TypeError, ValueError):
            ts = None
        desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        items.append({"source": source, "title": title, "link": link,
                      "published": ts.isoformat() if ts else None,
                      "summary": re.sub(r"\s+", " ", desc).strip()[:280]})
    return items


def tag(title: str, source: str) -> list[str]:
    t = title.lower()
    tags = [name for name, rx in TAGS.items() if re.search(rx, t)]
    if source == "RBI" and "RBI & rates" not in tags:
        tags.insert(0, "RBI & rates")
    return tags or ["Other"]


def norm(title: str) -> str:
    # Google News appends " - Publisher"; strip it so the same story from two feeds dedupes.
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+-\s+[^-]+$", "", title.lower()))[:80]


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Indian market RSS headlines.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-age-hours", type=float, default=None, help="default 48, or 168 with --weekly")
    ap.add_argument("--weekly", action="store_true", help="weekend digest: 7 days of news plus IPO news")
    args = ap.parse_args()
    feeds = {**FEEDS, **WEEKLY_FEEDS} if args.weekly else FEEDS
    max_age = args.max_age_hours or (168 if args.weekly else 48)
    limit = 400 if args.weekly else 200

    def safe(item):
        source, url = item
        try:
            return source, fetch(source, url), None
        except Exception as exc:  # one dead feed must not empty the page
            return source, [], str(exc)[:200]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(safe, feeds.items()))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age)
    seen, items = set(), []
    for _, feed_items, _ in results:
        for it in feed_items:
            key = norm(it["title"])
            if key in seen:
                continue
            if it["published"] and datetime.fromisoformat(it["published"]) < cutoff:
                continue
            seen.add(key)
            items.append({**it, "tags": tag(it["title"], it["source"])})
    items.sort(key=lambda x: x["published"] or "", reverse=True)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {s: ({"ok": True, "items": len(i)} if err is None else {"ok": False, "error": err})
                    for s, i, err in results},
        "items": items[:limit],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for v in out["sources"].values() if v["ok"])
    print(f"wrote {args.out}: {len(out['items'])} headlines from {ok}/{len(feeds)} feeds")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
