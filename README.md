# Othello rating pipeline

Computes the LIVE World Othello FIDE-Elo rating (shift-1800 scale) and publishes it to
[worldothellorating](https://tomschotte-personal.github.io/worldothellorating/).

## How it works

`.github/workflows/live-refresh.yml` runs every 15 minutes:

1. The cron only fires on **weekends** (Sat/Sun) — weekday events need a manual run (workflow_dispatch).
2. Reads the `FTD_IDS` repository **variable** (Settings → Secrets and variables → Actions → Variables).
   - **Absent/empty → the run exits immediately** (a few seconds, effectively free). This is the off switch
     (`gh variable delete FTD_IDS --repo tomschotte-personal/othello-rating-pipeline` — GitHub rejects empty values).
   - Set it to space-separated FlipTheDisc tournament IDs to activate:
     `gh variable set FTD_IDS --repo tomschotte-personal/othello-rating-pipeline --body "559 591 573"`
   - **Remember to delete it again after the weekend** — otherwise the pipeline loops indefinitely.
2. Fetches those tournaments from flipthedisc.com (Playwright). A failed fetch falls back to the
   committed `tournament_<id>.json` cache instead of aborting.
3. Recomputes the LIVE rating on top of the monthly baseline (`shift1800_live.py`), regenerates the
   full HTML (`shift1800_html.py`), and pushes `index.html` to the `worldothellorating` Pages repo
   via the `PAGES_DEPLOY_KEY` secret (write deploy key).

Manual run: Actions → *Live rating refresh* → *Run workflow* (optionally passing IDs, which
override the variable).

## Monthly baseline updates

The monthly snapshots (`fide_rating/world_fide_v2_shift1800_*.json`) and the tournament archive
(`wof_results/`) are maintained locally and committed here when the monthly WOF list lands.
`BASELINE_DATE` in `fide_rating/shift1800_live.py` must match the newest snapshot.
