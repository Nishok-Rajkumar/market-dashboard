# On-time updates with an external timer

GitHub's built-in schedule can start runs hours late. A free timer service (cron-job.org) can instead ask GitHub
to start the run at the exact minute; GitHub then starts it within seconds. GitHub's own schedule stays on as a
backup, and a duplicate run is harmless because each run writes to the folder of the NSE session it covers.

## 1. Create a GitHub token that can only start this repo's workflows

1. Open https://github.com/settings/personal-access-tokens/new (Fine-grained token).
2. **Token name:** `market-dashboard timer` · **Expiration:** 1 year (put a reminder in your calendar).
3. **Repository access:** *Only select repositories* → `market-dashboard`.
4. **Permissions → Repository permissions → Actions:** *Read and write*. Leave everything else as *No access*.
5. **Generate token** and copy it (starts with `github_pat_`). It is shown only once.

This token can only start or cancel workflow runs in this one repository. It cannot read your other repos or
change code.

## 2. Create three jobs on cron-job.org

Sign up at https://cron-job.org (free), then **Create cronjob** three times with these settings.

Common to all three:

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/Nishok-Rajkumar/market-dashboard/actions/workflows/daily.yml/dispatches` |
| Advanced → Request method | `POST` |
| Advanced → Headers | `Authorization: Bearer <your github_pat_ token>` · `Accept: application/vnd.github+json` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json` |
| Advanced → Time zone | `Asia/Kolkata` |
| Schedule | Custom: Monday–Friday at the time below |

The three jobs:

| Title | Time (IST) | Request body |
|---|---|---|
| Market dashboard — full | 20:15 | `{"ref":"main","inputs":{"mode":"full"}}` |
| Market dashboard — night news | 23:15 | `{"ref":"main","inputs":{"mode":"news"}}` |
| Market dashboard — morning | 08:30 | `{"ref":"main","inputs":{"mode":"morning"}}` |

Use **Test run** on each job: a `204` response means GitHub accepted it, and a new run appears under
**Actions → Daily market data** within a few seconds.

## Troubleshooting

| Response | Meaning |
|---|---|
| 204 | Started |
| 401 | Token wrong or expired: make a new one and update the three jobs |
| 403 | Token lacks *Actions: Read and write* on this repo |
| 404 | URL typo, or the token doesn't include this repository |
| 422 | Body wrong: check the JSON and that `mode` is `full`, `news` or `morning` |
