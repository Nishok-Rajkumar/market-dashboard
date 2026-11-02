# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas>=2.0"]
# ///
"""NSE Option Chain Analyzer.

Fetches the live/last NSE option chain for an index (NIFTY, BANKNIFTY, FINNIFTY,
MIDCPNIFTY, NIFTYNXT50) or an F&O stock and reports:

  * PCR (OI) - whole chain and +/-10 strikes around ATM; PCR of change in OI
  * Max pain (strike where option writers' total payout is lowest)
  * Highest call OI strikes (resistance) and put OI strikes (support)
  * Largest fresh OI additions / unwinding today
  * ATM IV, ATM straddle premium -> expected move to expiry, IV skew (OTM put vs OTM call)

Usage:
  uv run scripts/nse_option_chain.py NIFTY
  uv run scripts/nse_option_chain.py BANKNIFTY --expiry 25-Nov-2026
  uv run scripts/nse_option_chain.py RELIANCE
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
API = "https://www.nseindia.com/api/"
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def nse_json(path: str) -> dict:
    req = urllib.request.Request(API + path, headers={
        "User-Agent": UA, "Referer": "https://www.nseindia.com/option-chain", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            if attempt == 2:
                raise SystemExit(f"error: NSE request failed for {path}: {exc}")
            time.sleep(1.5)
    return {}


def load_chain(symbol: str, expiry: str | None) -> tuple[pd.DataFrame, float, str, str, list[str]]:
    q = urllib.parse.quote(symbol)
    info = nse_json(f"option-chain-contract-info?symbol={q}")
    expiries = info.get("expiryDates", [])
    if not expiries:
        raise SystemExit(f"error: no F&O expiries found for {symbol} (is it in the F&O segment?)")
    expiry = expiry or expiries[0]
    kind = "Indices" if symbol in INDICES else "Equity"
    data = nse_json(f"option-chain-v3?type={kind}&symbol={q}&expiry={urllib.parse.quote(expiry)}")
    rec = data.get("records", {})
    rows = []
    for d in rec.get("data", []):
        ce, pe = d.get("CE") or {}, d.get("PE") or {}
        rows.append({
            "strike": float(d["strikePrice"]),
            "ce_oi": ce.get("openInterest", 0) or 0, "ce_chg_oi": ce.get("changeinOpenInterest", 0) or 0,
            "ce_ltp": ce.get("lastPrice", 0) or 0, "ce_iv": ce.get("impliedVolatility", 0) or 0,
            "ce_vol": ce.get("totalTradedVolume", 0) or 0,
            "pe_oi": pe.get("openInterest", 0) or 0, "pe_chg_oi": pe.get("changeinOpenInterest", 0) or 0,
            "pe_ltp": pe.get("lastPrice", 0) or 0, "pe_iv": pe.get("impliedVolatility", 0) or 0,
            "pe_vol": pe.get("totalTradedVolume", 0) or 0,
        })
    if not rows:
        raise SystemExit(f"error: empty option chain for {symbol} {expiry}")
    df = pd.DataFrame(rows).groupby("strike", as_index=False).sum().sort_values("strike").reset_index(drop=True)
    return df, float(rec.get("underlyingValue", 0)), rec.get("timestamp", ""), expiry, expiries


def max_pain(df: pd.DataFrame) -> float:
    strikes = df["strike"].to_numpy()
    pain = [((s - strikes).clip(min=0) * df["ce_oi"]).sum() + ((strikes - s).clip(min=0) * df["pe_oi"]).sum()
            for s in strikes]
    return float(strikes[int(pd.Series(pain).idxmin())])


def analyze(symbol: str, expiry: str | None) -> dict:
    df, spot, ts, expiry, expiries = load_chain(symbol, expiry)
    atm_idx = int((df["strike"] - spot).abs().idxmin())
    atm = df.loc[atm_idx]
    near = df.iloc[max(0, atm_idx - 10): atm_idx + 11]

    def pcr(p: pd.Series, c: pd.Series) -> float | None:
        return round(float(p.sum()) / float(c.sum()), 2) if c.sum() else None

    straddle = float(atm["ce_ltp"] + atm["pe_ltp"])
    step = float(df["strike"].diff().median())
    otm_put = df[df["strike"] <= spot * 0.97].tail(1)
    otm_call = df[df["strike"] >= spot * 1.03].head(1)
    skew = None
    if len(otm_put) and len(otm_call) and otm_put["pe_iv"].iloc[0] and otm_call["ce_iv"].iloc[0]:
        skew = round(float(otm_put["pe_iv"].iloc[0] - otm_call["ce_iv"].iloc[0]), 2)

    def top(col: str, n: int = 3, ascending: bool = False) -> list[dict]:
        t = df.sort_values(col, ascending=ascending).head(n)
        return [{"strike": s, col: int(v)} for s, v in zip(t["strike"], t[col])]

    days_to_exp = (datetime.strptime(expiry, "%d-%b-%Y") - datetime.now()).days + 1
    pcr_all = pcr(df["pe_oi"], df["ce_oi"])
    if pcr_all is None:
        bias = "n/a"
    elif pcr_all >= 1.3:
        bias = "Heavy put writing (bullish support) — but > 1.5 can mean over-crowded / contrarian top risk"
    elif pcr_all >= 1.0:
        bias = "Mildly bullish (puts written more than calls)"
    elif pcr_all >= 0.7:
        bias = "Neutral to mildly bearish"
    else:
        bias = "Bearish (call writing dominates) — < 0.5 can mean oversold / contrarian bounce risk"

    return {
        "symbol": symbol, "expiry": expiry, "next_expiries": expiries[:6], "data_timestamp": ts,
        "spot": spot, "atm_strike": float(atm["strike"]), "strike_step": step, "days_to_expiry": days_to_exp,
        "pcr_oi_total": pcr_all, "pcr_oi_near_atm": pcr(near["pe_oi"], near["ce_oi"]),
        "pcr_change_oi": pcr(df["pe_chg_oi"].clip(lower=0), df["ce_chg_oi"].clip(lower=0)),
        "pcr_bias": bias,
        "max_pain": max_pain(df),
        "resistance_call_oi": top("ce_oi"), "support_put_oi": top("pe_oi"),
        "fresh_call_writing": top("ce_chg_oi"), "fresh_put_writing": top("pe_chg_oi"),
        "call_unwinding": top("ce_chg_oi", ascending=True), "put_unwinding": top("pe_chg_oi", ascending=True),
        "atm_iv_call": float(atm["ce_iv"]), "atm_iv_put": float(atm["pe_iv"]),
        "atm_straddle": round(straddle, 2),
        "expected_move_pts": round(straddle * 0.85, 2),  # straddle ~ 1.25 SD; 0.85x ~ 1 SD
        "expected_range": [round(spot - straddle * 0.85, 2), round(spot + straddle * 0.85, 2)],
        "iv_skew_put_minus_call_3pct_otm": skew,
        "chain_near_atm": near.to_dict(orient="records"),
    }


def to_markdown(r: dict) -> str:
    def fmt(items: list[dict], col: str) -> str:
        return ", ".join(f"{int(x['strike'])} ({x[col]:,})" for x in items)

    L = [f"# {r['symbol']} Option Chain — expiry {r['expiry']} ({r['days_to_expiry']} days)",
         f"_NSE data timestamp: {r['data_timestamp']}_", "",
         f"- **Spot:** {r['spot']:,}  |  ATM strike {int(r['atm_strike'])}  |  **Max pain:** {int(r['max_pain'])}",
         f"- **PCR (OI):** total {r['pcr_oi_total']}, near ATM {r['pcr_oi_near_atm']}, fresh OI {r['pcr_change_oi']} → {r['pcr_bias']}",
         f"- **Resistance (max call OI):** {fmt(r['resistance_call_oi'], 'ce_oi')}",
         f"- **Support (max put OI):** {fmt(r['support_put_oi'], 'pe_oi')}",
         f"- **Fresh call writing:** {fmt(r['fresh_call_writing'], 'ce_chg_oi')}",
         f"- **Fresh put writing:** {fmt(r['fresh_put_writing'], 'pe_chg_oi')}",
         f"- **Call unwinding:** {fmt(r['call_unwinding'], 'ce_chg_oi')}  |  **Put unwinding:** {fmt(r['put_unwinding'], 'pe_chg_oi')}",
         f"- **ATM IV:** call {r['atm_iv_call']}%, put {r['atm_iv_put']}%  |  IV skew (3% OTM put − call): {r['iv_skew_put_minus_call_3pct_otm']}",
         f"- **ATM straddle:** {r['atm_straddle']} → expected move ±{r['expected_move_pts']} "
         f"(≈1 SD range {r['expected_range'][0]:,} – {r['expected_range'][1]:,})",
         f"- Next expiries: {', '.join(r['next_expiries'])}", "",
         "## Chain around ATM",
         "| CE OI | CE ΔOI | CE LTP | CE IV | Strike | PE IV | PE LTP | PE ΔOI | PE OI |",
         "|---|---|---|---|---|---|---|---|---|"]
    for x in r["chain_near_atm"]:
        mark = "**" if x["strike"] == r["atm_strike"] else ""
        L.append(f"| {x['ce_oi']:,} | {x['ce_chg_oi']:+,} | {x['ce_ltp']} | {x['ce_iv']} | {mark}{int(x['strike'])}{mark} "
                 f"| {x['pe_iv']} | {x['pe_ltp']} | {x['pe_chg_oi']:+,} | {x['pe_oi']:,} |")
    L += ["", "_OI is in contracts as reported by NSE. Process tool, not investment advice._"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE option chain analyzer.")
    ap.add_argument("symbol", help="NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 or an F&O stock symbol")
    ap.add_argument("--expiry", help="DD-Mon-YYYY, default nearest")
    ap.add_argument("--output-dir", default="reports/data")
    args = ap.parse_args()

    r = analyze(args.symbol.upper().strip(), args.expiry)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"nse_oc_{r['symbol']}_{r['expiry']}_{datetime.now():%Y-%m-%d}"
    (out / f"{stem}.json").write_text(json.dumps(r, indent=2, default=str))
    (out / f"{stem}.md").write_text(to_markdown(r))
    print(f"JSON report: {out / (stem + '.json')}")
    print(f"Markdown report: {out / (stem + '.md')}")
    print(f"\n{r['symbol']} {r['expiry']}: spot {r['spot']}, PCR {r['pcr_oi_total']}, max pain {int(r['max_pain'])}, "
          f"expected move ±{r['expected_move_pts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
