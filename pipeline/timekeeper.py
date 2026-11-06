# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Start the daily workflow on time, even though GitHub's scheduler runs hours late.

GitHub starts this script every 30 minutes (late, but often). Each time it:
  - starts a missed update straight away (no daily run since the update was due), or
  - waits until an update due within the next 90 minutes, then starts it, or
  - exits.

Updates (IST, Mon–Fri): 20:15 full · 23:15 news · 08:30 morning.

Usage (in GitHub Actions, with GITHUB_TOKEN and GITHUB_REPOSITORY set):
  uv run pipeline/timekeeper.py
  uv run pipeline/timekeeper.py --dry-run --now 2026-11-06T19:10   # show the decision only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SLOTS = [((20, 15), "full"), ((23, 15), "news"), ((8, 30), "morning")]
WAIT_AHEAD = timedelta(minutes=90)  # how long one wake-up may wait for an update
CATCH_UP = timedelta(hours=8)       # how late a missed update is still worth starting
API = "https://api.github.com"


def slots_around(now: datetime) -> list[tuple[datetime, str]]:
    """Weekday update times from yesterday to tomorrow, sorted."""
    out = []
    for offset in (-1, 0, 1):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() >= 5:
            continue
        for (h, m), mode in SLOTS:
            out.append((datetime(day.year, day.month, day.day, h, m, tzinfo=IST), mode))
    return sorted(out)


def gh(path: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{API}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}", method=method,
                                 data=json.dumps(body).encode() if body else None, headers={
                                     "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                     "Accept": "application/vnd.github+json", "User-Agent": "stockverse-timekeeper"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def ran_since(t: datetime) -> bool:
    """Has the daily workflow started (by any trigger) since a little before t?"""
    since = (t - timedelta(minutes=10)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = gh(f"actions/workflows/daily.yml/runs?created=%3E%3D{since}&per_page=5").get("workflow_runs", [])
    return any(r.get("conclusion") not in ("cancelled", "skipped") for r in runs)


def start(mode: str) -> None:
    gh("actions/workflows/daily.yml/dispatches", "POST", {"ref": "main", "inputs": {"mode": mode}})


def decide(now: datetime, already_ran) -> tuple[str, datetime | None, str | None]:
    """Return (action, when, mode): action is 'now', 'wait' or 'none'."""
    slots = slots_around(now)
    past = [s for s in slots if s[0] <= now and now - s[0] <= CATCH_UP]
    future = [s for s in slots if s[0] > now]
    if past and not already_ran(past[-1][0]):
        # Something is overdue. A missed full update wins, since it also refreshes news and the brief.
        missed_full = [s for s in past if s[1] == "full" and not already_ran(s[0])]
        t, mode = missed_full[-1] if missed_full else past[-1]
        return "now", t, mode
    if future and future[0][0] - now <= WAIT_AHEAD:
        return "wait", future[0][0], future[0][1]
    return "none", None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Start the daily workflow on time.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="pretend it is this IST time, e.g. 2026-11-06T19:10 (with --dry-run)")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now).replace(tzinfo=IST) if args.now else datetime.now(IST)
    already_ran = (lambda t: False) if args.dry_run and args.now else ran_since
    action, when, mode = decide(now, already_ran)
    print(f"{now:%a %d %b %H:%M} IST → {action}" + (f" {mode} (due {when:%a %H:%M})" if when else ""))
    if args.dry_run or action == "none":
        return 0
    if action == "wait":
        time.sleep(max(0, (when - datetime.now(IST)).total_seconds()))
        if ran_since(when):  # another trigger beat us to it
            print("already started by another trigger")
            return 0
    start(mode)
    print(f"started daily.yml mode={mode} at {datetime.now(IST):%H:%M:%S} IST")
    return 0


if __name__ == "__main__":
    sys.exit(main())
