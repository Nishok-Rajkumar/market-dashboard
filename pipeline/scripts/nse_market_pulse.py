# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0"]
# ///
"""NSE Market Pulse — the short-term daily dashboard.

Sections:
  1. Global & India snapshot: Nifty 50, Bank Nifty, India VIX, USD-INR, Brent, Gold,
     S&P 500 futures, Nasdaq futures (1-day / 5-day change).
  2. FII/DII cash-market flows from NSE (Rs crore). NSE only serves the latest day, so
     each run appends to state/fii_dii_history.csv; streaks and 5/20-day sums grow over time.
  3. F&O ban list (securities in ban period for the trade date).
  4. Delivery analysis from NSE bhavcopy (Nifty 500 names): delivery-quantity spikes
     vs the stock's 10-session average, tagged ACCUMULATION (price up) or DISTRIBUTION (price down).
  5. Top gainers / losers in the Nifty 500.
  6. Corporate results / board meetings for Nifty 500 companies in the next N days.

Usage:
  uv run scripts/nse_market_pulse.py [--output-dir reports] [--state-dir state] [--days-ahead 7]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
NSE_API = "https://www.nseindia.com/api/"
BHAV_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
BAN_URL = "https://archives.nseindia.com/content/fo/fo_secban.csv"
N500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
CACHE_DIR = Path.home() / ".cache" / "nse-skills"

SNAPSHOT = {
    "^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "^INDIAVIX": "India VIX", "^CRSLDX": "Nifty 500",
    "INR=X": "USD-INR", "BZ=F": "Brent crude ($)", "GC=F": "Gold ($)",
    "ES=F": "S&P 500 fut", "NQ=F": "Nasdaq 100 fut", "^N225": "Nikkei 225", "^HSI": "Hang Seng",
}


def http_get(url: str, referer: str = "https://www.nseindia.com/", timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def nse_json(path: str, referer: str = "https://www.nseindia.com/") -> object:
    for attempt in range(3):
        try:
            return json.loads(http_get(NSE_API + path, referer))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            if attempt == 2:
                raise
            time.sleep(1.5)
            print(f"retrying {path}: {exc}", file=sys.stderr)


def nifty500() -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "ind_nifty500list.csv"
    if not (cached.exists() and time.time() - cached.stat().st_mtime < 7 * 86400):
        cached.write_bytes(http_get(N500_URL))
    return pd.read_csv(cached)


def snapshot() -> list[dict]:
    d = yf.download(list(SNAPSHOT), period="1mo", interval="1d", progress=False, auto_adjust=True)["Close"]
    rows = []
    for t, name in SNAPSHOT.items():
        s = d[t].dropna() if t in d else pd.Series(dtype=float)
        if len(s) < 6:
            continue
        rows.append({"name": name, "last": round(float(s.iloc[-1]), 2), "date": s.index[-1].strftime("%Y-%m-%d"),
                     "chg_1d_pct": round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2),
                     "chg_5d_pct": round((s.iloc[-1] / s.iloc[-6] - 1) * 100, 2)})
    return rows


def fii_dii(state_dir: Path) -> dict:
    data = nse_json("fiidiiTradeReact")
    hist_path = state_dir / "fii_dii_history.csv"
    state_dir.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([{
        "date": datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat(),
        "category": "FII" if "FII" in r["category"] else "DII",
        "buy_cr": float(r["buyValue"]), "sell_cr": float(r["sellValue"]), "net_cr": float(r["netValue"]),
    } for r in data])
    hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame(columns=new.columns)
    hist = (pd.concat([hist, new]).drop_duplicates(subset=["date", "category"], keep="last")
            .sort_values(["date", "category"]))
    hist.to_csv(hist_path, index=False)

    out = {"latest": new.to_dict(orient="records"), "history_days": int(hist["date"].nunique())}
    for cat in ("FII", "DII"):
        h = hist[hist.category == cat].sort_values("date")
        nets = h["net_cr"].tolist()
        streak = 0
        for v in reversed(nets):
            if streak == 0 or (v > 0) == (streak > 0):
                streak += 1 if v > 0 else -1
            else:
                break
        out[cat] = {"sum_5d_cr": round(sum(nets[-5:]), 2), "sum_20d_cr": round(sum(nets[-20:]), 2),
                    "days_available": len(nets), "streak_days": streak}
    return out


def ban_list() -> dict:
    raw = http_get(BAN_URL).decode("utf-8").strip().splitlines()
    header = raw[0] if raw else ""
    names = [line.split(",")[1].strip() for line in raw[1:] if "," in line]
    return {"header": header, "symbols": names}


def bhavcopies(n: int = 11) -> list[tuple[date, pd.DataFrame]]:
    """Last n available NSE full bhavcopies (with delivery data), newest first. Cached on disk."""
    bdir = CACHE_DIR / "bhavcopy"
    bdir.mkdir(parents=True, exist_ok=True)
    out, d, misses = [], date.today(), 0
    while len(out) < n and misses < 12:
        if d.weekday() < 5:
            key = d.strftime("%d%m%Y")
            f = bdir / f"{key}.csv"
            if not f.exists():
                try:
                    f.write_bytes(http_get(BHAV_URL.format(d=key), "https://www.nseindia.com/all-reports"))
                except urllib.error.HTTPError:
                    misses += 1  # holiday or not yet published
                    d -= timedelta(days=1)
                    continue
            df = pd.read_csv(f, skipinitialspace=True)
            df.columns = [c.strip() for c in df.columns]
            df = df[df["SERIES"].str.strip() == "EQ"].copy()
            df["SYMBOL"] = df["SYMBOL"].str.strip()
            for col in ("CLOSE_PRICE", "PREV_CLOSE", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER", "TURNOVER_LACS"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            out.append((d, df.set_index("SYMBOL")))
        d -= timedelta(days=1)
    for f in sorted(bdir.glob("*.csv"), key=lambda p: p.stat().st_mtime)[:-30]:
        f.unlink()  # keep the cache small
    return out


def delivery_and_movers(universe: set[str], industry: dict[str, str]) -> dict:
    books = bhavcopies()
    if len(books) < 3:
        return {"error": "could not download enough bhavcopy files"}
    day, today = books[0]
    today = today[today.index.isin(universe)].copy()
    past = pd.concat([b["DELIV_QTY"] for _, b in books[1:]], axis=1)
    today["deliv_avg10"] = past.reindex(today.index).mean(axis=1)
    today["deliv_x"] = today["DELIV_QTY"] / today["deliv_avg10"]
    today["chg_pct"] = (today["CLOSE_PRICE"] / today["PREV_CLOSE"] - 1) * 100
    today["industry"] = today.index.map(industry)

    def rec(df: pd.DataFrame) -> list[dict]:
        return [{"symbol": s, "industry": r.industry, "close": round(r.CLOSE_PRICE, 2), "chg_pct": round(r.chg_pct, 2),
                 "deliv_pct": round(r.DELIV_PER, 1), "deliv_x_avg10": round(r.deliv_x, 2),
                 "turnover_cr": round(r.TURNOVER_LACS / 100, 1)} for s, r in df.iterrows()]

    spikes = today[(today["deliv_x"] >= 2) & (today["DELIV_PER"] >= 50) & (today["TURNOVER_LACS"] >= 500)]
    return {
        "bhavcopy_date": day.isoformat(), "sessions_used": len(books),
        "accumulation": rec(spikes[spikes.chg_pct > 0].sort_values("deliv_x", ascending=False).head(15)),
        "distribution": rec(spikes[spikes.chg_pct < 0].sort_values("deliv_x", ascending=False).head(15)),
        "top_gainers": rec(today.sort_values("chg_pct", ascending=False).head(10)),
        "top_losers": rec(today.sort_values("chg_pct").head(10)),
        "advances": int((today.chg_pct > 0).sum()), "declines": int((today.chg_pct < 0).sum()),
    }


def upcoming_results(universe: set[str], days_ahead: int) -> list[dict]:
    events = nse_json("event-calendar")
    horizon = date.today() + timedelta(days=days_ahead)
    out = []
    for e in events:
        try:
            d = datetime.strptime(e["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if date.today() <= d <= horizon and e.get("symbol") in universe:
            out.append({"date": d.isoformat(), "symbol": e["symbol"], "purpose": e.get("purpose", "")})
    return sorted(out, key=lambda x: (x["date"], x["symbol"]))


def section(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # one failing source must not kill the whole pulse
        print(f"warning: {fn.__name__} failed: {exc}", file=sys.stderr)
        return {"error": str(exc)}


def to_markdown(r: dict) -> str:
    L = [f"# NSE Market Pulse — {r['generated_at'][:10]}", ""]
    L += ["## Snapshot", "| Market | Last | 1D % | 5D % | As of |", "|---|---|---|---|---|"]
    for s in r["snapshot"] if isinstance(r["snapshot"], list) else []:
        L.append(f"| {s['name']} | {s['last']} | {s['chg_1d_pct']} | {s['chg_5d_pct']} | {s['date']} |")

    f = r["fii_dii"]
    L += ["", "## FII / DII cash flows (Rs crore)"]
    if "error" in f:
        L.append(f"_unavailable: {f['error']}_")
    else:
        for x in f["latest"]:
            L.append(f"- **{x['category']}** {x['date']}: buy {x['buy_cr']:,.0f} / sell {x['sell_cr']:,.0f} → **net {x['net_cr']:+,.0f}**")
        for cat in ("FII", "DII"):
            c = f[cat]
            L.append(f"- {cat}: 5-day sum {c['sum_5d_cr']:+,.0f}, 20-day sum {c['sum_20d_cr']:+,.0f}, "
                     f"streak {c['streak_days']:+d} days (history: {c['days_available']} days)")
        if f["history_days"] < 20:
            L.append(f"- _History builds up one day per run ({f['history_days']} so far) — run daily for meaningful sums._")

    b = r["fo_ban"]
    L += ["", "## F&O ban list"]
    L.append(f"_{b.get('header', '')}_: " + (", ".join(b.get("symbols", [])) or "none") if "error" not in b else f"_unavailable: {b['error']}_")

    d = r["delivery"]
    L += ["", f"## Delivery & movers (Nifty 500, bhavcopy {d.get('bhavcopy_date', 'n/a')})"]
    if "error" in d:
        L.append(f"_unavailable: {d['error']}_")
    else:
        L.append(f"Advances / declines: {d['advances']} / {d['declines']}")
        for key, title in (("accumulation", "Delivery spikes with price UP (possible accumulation)"),
                           ("distribution", "Delivery spikes with price DOWN (possible distribution)"),
                           ("top_gainers", "Top gainers"), ("top_losers", "Top losers")):
            L += ["", f"### {title}", "| Symbol | Industry | Close | Chg % | Deliv % | Deliv x 10d avg | Turnover Cr |", "|---|---|---|---|---|---|---|"]
            for x in d[key] or []:
                L.append(f"| {x['symbol']} | {x['industry']} | {x['close']} | {x['chg_pct']} | {x['deliv_pct']} | {x['deliv_x_avg10']} | {x['turnover_cr']} |")
            if not d[key]:
                L.append("| — | | | | | | |")

    ev = r["upcoming_results"]
    L += ["", f"## Board meetings / results in next {r['days_ahead']} days (Nifty 500)"]
    if isinstance(ev, dict):
        L.append(f"_unavailable: {ev['error']}_")
    else:
        L += ["| Date | Symbol | Purpose |", "|---|---|---|"] + [f"| {e['date']} | {e['symbol']} | {e['purpose']} |" for e in ev]
    L += ["", "_Process tool, not investment advice. FII/DII figures are provisional NSE data._"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE daily market pulse.")
    ap.add_argument("--output-dir", default="reports/data")
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--days-ahead", type=int, default=7)
    args = ap.parse_args()

    cons = nifty500()
    universe = set(cons["Symbol"].str.strip())
    industry = dict(zip(cons["Symbol"].str.strip(), cons["Industry"]))

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days_ahead": args.days_ahead,
        "snapshot": section(snapshot),
        "fii_dii": section(fii_dii, Path(args.state_dir)),
        "fo_ban": section(ban_list),
        "delivery": section(delivery_and_movers, universe, industry),
        "upcoming_results": section(upcoming_results, universe, args.days_ahead),
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"nse_pulse_{date.today().isoformat()}"
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str))
    (out / f"{stem}.md").write_text(to_markdown(result))
    print(f"JSON report: {out / (stem + '.json')}")
    print(f"Markdown report: {out / (stem + '.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
