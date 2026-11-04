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
  uv run pipeline/run_daily.py --skip swing # skip slow steps while testing
"""

from __future__ import annotations

import argparse
import csv
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
            url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": ua, "Referer": "https://www.nseindia.com/"})
            try:
                with urllib.request.urlopen(req, timeout=20):
                    return d
            except urllib.error.HTTPError:
                pass  # holiday, or not published yet
            except urllib.error.URLError:
                break
        d -= timedelta(days=1)
    return today


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily dashboard data run.")
    ap.add_argument("--mode", choices=["full", "news", "morning"], default="full")
    ap.add_argument("--skip", nargs="*", default=[],
                    help="steps to skip: pulse breadth sectors options swing levels participant_oi heatmap")
    args = ap.parse_args()

    now = datetime.now(IST)
    DATA.mkdir(exist_ok=True)
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

    if args.mode == "morning" and (day / "pulse.json").exists():
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
