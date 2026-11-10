# On-time updates with an external timer

GitHub's built-in schedule can start runs hours late (it woke the Timekeeper only about 4 times a day instead of
48). A free timer service (cron-job.org) pokes the Timekeeper every 15 minutes instead; GitHub starts it within
seconds, and the Timekeeper starts each update at its exact minute (or catches up one that was missed). All the
update times stay in one place, `pipeline/timekeeper.py`, so the timer never needs changing.

## 1. Create a GitHub token that can only start this repo's workflows

1. Open https://github.com/settings/personal-access-tokens/new (Fine-grained token).
2. **Token name:** `market-dashboard timer` · **Expiration:** 1 year (put a reminder in your calendar).
3. **Repository access:** *Only select repositories* → `market-dashboard`.
4. **Permissions → Repository permissions → Actions:** *Read and write*. Leave everything else as *No access*.
5. **Generate token** and copy it (starts with `github_pat_`). It is shown only once.

This token can only start or cancel workflow runs in this one repository. It cannot read your other repos or
change code.

## 2. Create one job on cron-job.org

Sign up at https://cron-job.org (free), then **Create cronjob** with:

| Field | Value |
|---|---|
| Title | `StockVerse timekeeper` |
| URL | `https://api.github.com/repos/Nishok-Rajkumar/market-dashboard/actions/workflows/timekeeper.yml/dispatches` |
| Schedule | Every 15 minutes |
| Advanced → Request method | `POST` |
| Advanced → Headers (add four) | `Authorization` = `Bearer <your github_pat_ token>` · `Accept` = `application/vnd.github+json` · `X-GitHub-Api-Version` = `2022-11-28` · `Content-Type` = `application/json` |
| Advanced → Request body | `{"ref":"main"}` |

Press **Test run**: `204` means GitHub accepted it, and a new run appears under **Actions → Timekeeper** within a
few seconds. Most pokes find nothing due and finish in seconds; near an update time the Timekeeper waits for the
exact minute (a newer poke takes over the wait, so you will see some runs marked *cancelled* — that is normal).

## Troubleshooting

| Response | Meaning |
|---|---|
| 204 | Started |
| 401 | Token wrong or expired (header must be `Bearer ` + token): make a new one and update the job |
| 403 | Token lacks *Actions: Read and write* on this repo |
| 404 | URL typo, or the token doesn't include this repository |
| 422 | Body wrong: it must be exactly `{"ref":"main"}` |
