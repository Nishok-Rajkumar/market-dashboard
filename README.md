# Market Pulse India

A personal Indian stock market dashboard that updates itself every trading day from free public data, so
the Mac doesn't need to be on. For learning only, not investment advice.

- **Data**: NSE archives and APIs, Yahoo Finance, public RSS feeds (ET, Livemint, Business Standard, BusinessLine, RBI, Google News)
- **Summary**: an open-source model (Llama 3.3 70B by default) through **GitHub Models**, using the run's own `GITHUB_TOKEN`.
  Falls back to Groq (if `GROQ_API_KEY` is set), then to plain sentences built from the numbers.
- **Schedule** (GitHub Actions, Mon–Fri): 6:45 PM IST full run · 8:30 AM IST news + summary refresh
- **Site**: static HTML on GitHub Pages; reads `data/<date>/*.json`

## Layout

| Path | What |
|---|---|
| `pipeline/run_daily.py` | Runs every step, writes `data/<IST date>/` and `status.json` |
| `pipeline/scripts/` | Copies of the NSE skill scripts from `Market Reviewer/skills/*/scripts/` |
| `pipeline/levels.py` · `news.py` · `summarize.py` | Pivots · headlines · daily brief |
| `pipeline/check_sources.py` | Shows which sources answer from the current machine |
| `state/fii_dii_history.csv` | FII/DII history (NSE only serves the latest day, so it builds up per run) |
| `site/` | The dashboard (`index.html`, `app.js`, `style.css`) |
| `.github/workflows/` | `daily.yml` (data + deploy), `pages.yml` (deploy on site edits), `check-sources.yml` |

## Run locally

```bash
uv run pipeline/run_daily.py
```

```bash
python3 -m http.server 8765
```

Then open http://localhost:8765/site/

## One-time GitHub setup

1. Create a new **public** repo on github.com (e.g. `market-dashboard`), with no README.
2. Push this folder:
   ```bash
   git add -A && git commit -m "Initial dashboard" && git branch -M main
   git remote add origin https://github.com/<your-username>/market-dashboard.git
   git push -u origin main
   ```
3. Repo **Settings → Pages → Source: GitHub Actions**.
4. Repo **Settings → Actions → General → Workflow permissions: Read and write**.
5. **Actions → Check data sources → Run workflow.** The summary shows which NSE sources GitHub's servers can reach.
6. **Actions → Daily market data → Run workflow (full).** When it finishes, the site is at
   `https://<your-username>.github.io/market-dashboard/`.
7. Optional: add a `GROQ_API_KEY` secret (Settings → Secrets → Actions) as a backup model, or set a repo
   variable `GITHUB_MODELS_MODEL` to try another model from github.com/marketplace/models.

## If NSE blocks GitHub's servers

Sections that depend on `www.nseindia.com/api` (FII/DII, option chain, results calendar) will show
"unavailable" and the page will say which steps failed. Options:
- Run `uv run pipeline/run_daily.py` on the Mac when it's on, then commit and push `data/` and `state/`.
- Run the same command by cron on a small India-region VM (Student Pack credits: DigitalOcean Bangalore or
  Azure Central India) that pushes to this repo.

Note: the repo and site are public. Keep personal holdings out of it.
