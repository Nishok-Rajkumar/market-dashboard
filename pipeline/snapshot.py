# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""Refresh only the price snapshot (Nifty, VIX, USD-INR, crude, gold, US futures, Asia) inside a day's pulse.json.

Used by the morning run so overnight global moves show up without re-running the whole NSE pulse.

Usage:
  uv run pipeline/snapshot.py --pulse data/2026-11-02/pulse.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from nse_market_pulse import snapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the price snapshot in pulse.json.")
    ap.add_argument("--pulse", required=True)
    args = ap.parse_args()

    rows = snapshot()
    if not rows:
        print("error: no prices returned", file=sys.stderr)
        return 1
    path = Path(args.pulse)
    pulse = json.loads(path.read_text()) if path.exists() else {}
    pulse["snapshot"] = rows
    pulse["snapshot_updated_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    path.write_text(json.dumps(pulse, indent=2, default=str))
    print(f"wrote {path}: {len(rows)} prices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
