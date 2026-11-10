# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Run every data step and assemble data/<IST date>/ for the website.

Each step runs as its own `uv run` process, so one failing source (e.g. NSE blocking a cloud server)
never stops the rest. What worked is recorded in data/<date>/status.json.

Usage:
  uv run pipeline/run_daily.py                 # full evening run (after NSE's last file, ~8 PM IST)
  uv run pipeline/run_daily.py --mode news     # night: refresh headlines + summary only
  uv run pipeline/run_daily.py --mode morning  # morning: headlines + summary + overnight global prices
  uv run pipeline/run_daily.py --mode weekend  # Sat/Sun: week's news + IPO watch + weekend brief → data/weekend/
  uv run pipeline/run_daily.py --skip swing # skip slow steps while testing
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA, STATE, RAW = ROOT / "data", ROOT / "state", ROOT / ".raw"
SCRIPTS = ROOT / "pipeline" / "scripts"
IST = ZoneInfo("Asia/Kolkata")


def run(cmd: list[str], timeout: int = 900) -> tuple[bool, str]:
    t0 = time.time()
    try:
        p = subprocess.run(["uv", "run", "--quiet", "--script", *map(str, cmd)], cwd=ROOT,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    tail = (p.stderr.strip().splitlines() or p.stdout.strip().splitlines() or [""])[-1]
    print(f"  {'ok ' if p.returncode == 0 else 'ERR'} {Path(cmd[0]).name} ({time.time() - t0:.0f}s) {tail[:160]}")
    return p.returncode == 0, tail[:300]


def latest_session(today: date) -> date:
    """The latest NSE session with a published bhavcopy. Folders are named by this, not by the run date,
    because GitHub can start scheduled runs hours late (past midnight IST)."""
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    d = today
    for _ in range(10):
        if d.weekday() < 5:
            # NSE answers HEAD with 503 for every file, so use GET and read only the first bytes.
            url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Referer": "https://www.nseindia.com/"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    head = r.read(400).decode("utf-8", "replace")
                if "csv" in r.headers.get("Content-Type", "") and "SYMBOL" in head:
                    # On some holidays NSE republishes the previous session under today's name, so trust
                    # the date inside the file (DATE1), not the file name.
                    row = next(csv.DictReader(io.StringIO(head), skipinitialspace=True))
                    return datetime.strptime(row["DATE1"].strip(), "%d-%b-%Y").date()
            except urllib.error.HTTPError as exc:
                if exc.code != 404:  # 404 = holiday or not published yet; anything else means we can't tell
                    print(f"warning: session check got HTTP {exc.code}", file=sys.stderr)
                    break
            except urllib.error.URLError:
                break
        d -= timedelta(days=1)
    # Couldn't check: before ~7 PM IST today's session isn't final, so use the previous weekday.
    if datetime.now(IST).hour >= 19:
        return today
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def newest(pattern: str) -> Path | None:
    files = sorted(RAW.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def raw_step(name: str, cmd: list, pattern: str, dest: Path, status: dict) -> None:
    """Run a copied skill script into .raw/ and move its JSON to the day folder."""
    ok, msg = run(cmd)
    src = newest(pattern)
    if ok and src:
        shutil.copy(src, dest)
        status[name] = {"ok": True}
    else:
        status[name] = {"ok": False, "error": msg or "no output file"}


def section_errors(pulse: Path) -> dict:
    """The pulse script keeps going when a source fails; surface those per-section errors."""
    try:
        d = json.loads(pulse.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v["error"] for k, v in d.items() if isinstance(v, dict) and "error" in v}


def build_indexes() -> None:
    days = sorted(p.name for p in DATA.iterdir() if p.is_dir() and p.name[:2] == "20")
    (DATA / "index.json").write_text(json.dumps({"days": days}, indent=1))

    hist = []
    for d in days:
        try:
            b = json.loads((DATA / d / "breadth.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        hist.append({"date": b.get("as_of", d), "score": b["composite_score"], "zone": b["zone"],
                     "pct_above_50dma": b["breadth"]["pct_above_50dma"],
                     "pct_above_200dma": b["breadth"]["pct_above_200dma"]})
    (DATA / "breadth_history.json").write_text(json.dumps(hist, indent=1))

    fii = STATE / "fii_dii_history.csv"
    if fii.exists():
        with fii.open() as fh:
            rows = [{**r, **{k: float(r[k]) for k in ("buy_cr", "sell_cr", "net_cr")}} for r in csv.DictReader(fh)]
        (DATA / "fii_dii_history.json").write_text(json.dumps(rows, indent=1))


def run_weekend(now: datetime) -> int:
    """Weekend update. It has its own folder, named by the weekend's Saturday, so it never overwrites the
    last trading session's news and brief."""
    sat = now.date() - timedelta(days=(now.weekday() - 5) % 7)
    wk = DATA / "weekend" / sat.isoformat()
    wk.mkdir(parents=True, exist_ok=True)
    sessions = sorted(p for p in DATA.iterdir() if p.is_dir() and p.name[:2] == "20")
    print(f"run weekend → {wk.relative_to(ROOT)} (last session {sessions[-1].name if sessions else 'none'})")
    status: dict = {}

    ok, msg = run([ROOT / "pipeline" / "news.py", "--weekly", "--out", wk / "news.json"])
    status["news"] = {"ok": True} if ok else {"ok": False, "error": msg}
    ok, msg = run([ROOT / "pipeline" / "ipo.py", "--out", wk / "ipo.json"])
    status["ipo"] = {"ok": True} if ok else {"ok": False, "error": msg}
    if sessions:
        ok, msg = run([ROOT / "pipeline" / "summarize.py", "--weekend", "--day-dir", sessions[-1], "--ipo", wk / "ipo.json",
                       "--news", wk / "news.json", "--out", wk / "summary.json"], timeout=180)
        status["summary"] = {"ok": True} if ok else {"ok": False, "error": msg}

    stamp = now.isoformat(timespec="seconds")
    info = {"date": sat.isoformat(), "updated_at": stamp, "last_session": sessions[-1].name if sessions else None}
    (wk / "status.json").write_text(json.dumps({**info, "mode": "weekend", "steps": status}, indent=2))
    (DATA / "weekend" / "latest.json").write_text(json.dumps(info, indent=2))
    weekends = sorted(p.name for p in (DATA / "weekend").iterdir() if p.is_dir())
    (DATA / "weekend" / "index.json").write_text(json.dumps({"weekends": weekends}, indent=1))

    failed = [k for k, v in status.items() if not v.get("ok")]
    print(f"done: {len(status) - len(failed)}/{len(status)} steps ok" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily dashboard data run.")
    ap.add_argument("--mode", choices=["full", "news", "morning", "weekend"], default="full")
    ap.add_argument("--force", action="store_true", help="allow a full run during market hours")
    ap.add_argument("--skip", nargs="*", default=[],
                    help="steps to skip: pulse breadth sectors options swing levels participant_oi heatmap")
    args = ap.parse_args()

    now = datetime.now(IST)
    # A full run during market hours would mix live prices into the previous session's folder; this also
    # catches GitHub schedule runs that start many hours late.
    if args.mode == "full" and not args.force and now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (18, 30):
        print(f"skip: full run during market hours ({now:%H:%M} IST); news/morning modes are fine, or pass --force")
        return 0
    DATA.mkdir(exist_ok=True)
    if args.mode == "weekend":
        return run_weekend(now)
    if args.mode == "full":
        day = DATA / latest_session(now.date()).isoformat()
    else:  # news/morning refreshes attach to the latest full run
        days = sorted(p for p in DATA.iterdir() if p.is_dir() and p.name[:2] == "20")
        day = days[-1] if days else DATA / now.date().isoformat()
    day.mkdir(parents=True, exist_ok=True)
    status_path = day / "status.json"
    status = json.loads(status_path.read_text()).get("steps", {}) if status_path.exists() else {}

    print(f"run {args.mode} → {day.relative_to(ROOT)}")
    if args.mode == "full":
        shutil.rmtree(RAW, ignore_errors=True)
        RAW.mkdir()
        steps = {
            "pulse": ([SCRIPTS / "nse_market_pulse.py", "--output-dir", RAW, "--state-dir", STATE],
                      "nse_pulse_*.json", "pulse.json"),
            "breadth": ([SCRIPTS / "nse_breadth.py", "--output-dir", RAW], "nse_breadth_*.json", "breadth.json"),
            "sectors": ([SCRIPTS / "nse_sector_rotation.py", "--output-dir", RAW],
                        "nse_sector_rotation_*.json", "sectors.json"),
            "options_NIFTY": ([SCRIPTS / "nse_option_chain.py", "NIFTY", "--output-dir", RAW],
                              "nse_oc_NIFTY_*.json", "oc_NIFTY.json"),
            "options_BANKNIFTY": ([SCRIPTS / "nse_option_chain.py", "BANKNIFTY", "--output-dir", RAW],
                                  "nse_oc_BANKNIFTY_*.json", "oc_BANKNIFTY.json"),
            "swing": ([SCRIPTS / "nse_swing_screener.py", "--output-dir", RAW, "--top", "25"],
                      "nse_swing_*.json", "swing.json"),
        }
        for name, (cmd, pattern, dest) in steps.items():
            if name.split("_")[0] in args.skip:
                continue
            raw_step(name, cmd, pattern, day / dest, status)
        if status.get("pulse", {}).get("ok"):
            errs = section_errors(day / "pulse.json")
            if errs:
                status["pulse"]["section_errors"] = errs
        own = {
            "levels": [ROOT / "pipeline" / "levels.py", "--out", day / "levels.json"],
            "participant_oi": [ROOT / "pipeline" / "participant_oi.py", "--state", STATE, "--out", day / "participant_oi.json"],
            "heatmap": [ROOT / "pipeline" / "heatmap.py", "--out", day / "heatmap.json"],
            "corp_actions": [ROOT / "pipeline" / "corp_actions.py", "--out", day / "corp_actions.json"],
        }
        for name, cmd in own.items():
            if name in args.skip:
                continue
            ok, msg = run(cmd)
            status[name] = {"ok": True} if ok else {"ok": False, "error": msg}

    # Only before the open: later in the day the prices belong to a new session, not to this folder's
    # (GitHub has started the 8:30 AM run as late as 3:47 PM).
    if args.mode == "morning" and (now.weekday() >= 5 or now.hour < 9):
        pre_open = True
    else:
        pre_open = False
        if args.mode == "morning":
            print(f"skip snapshot: {now:%H:%M} IST is after the open; refreshing news and brief only")
    if args.mode == "morning" and pre_open and (day / "pulse.json").exists():
        ok, msg = run([ROOT / "pipeline" / "snapshot.py", "--pulse", day / "pulse.json"])
        status["snapshot"] = {"ok": True} if ok else {"ok": False, "error": msg}

    ok, msg = run([ROOT / "pipeline" / "news.py", "--out", DATA / "news.json"])
    status["news"] = {"ok": True} if ok else {"ok": False, "error": msg}
    if ok:
        shutil.copy(DATA / "news.json", day / "news.json")

    ok, msg = run([ROOT / "pipeline" / "summarize.py", "--day-dir", day, "--news", DATA / "news.json",
                   "--out", day / "summary.json"], timeout=180)
    status["summary"] = {"ok": True} if ok else {"ok": False, "error": msg}

    stamp = now.isoformat(timespec="seconds")
    status_path.write_text(json.dumps({"date": day.name, "updated_at": stamp, "mode": args.mode,
                                       "steps": status}, indent=2))
    (DATA / "latest.json").write_text(json.dumps({"date": day.name, "updated_at": stamp}, indent=2))
    build_indexes()
    shutil.rmtree(RAW, ignore_errors=True)

    failed = [k for k, v in status.items() if not v.get("ok")]
    print(f"done: {len(status) - len(failed)}/{len(status)} steps ok" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 0  # partial data is still worth publishing


if __name__ == "__main__":
    sys.exit(main())
