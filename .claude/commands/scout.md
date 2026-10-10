---
description: Run the full Stock Scout pipeline and agent review (weekly market-wide scan for big analyst-target disconnects)
argument-hint: "[--skip-pipeline] [--date YYYY-MM-DD]"
---

Run a Stock Scout cycle. Arguments: $ARGUMENTS

Keep your own context lean: you are the orchestrator. Agents read files and return short summaries; never print whole CSVs or research files yourself.

1. **Data** (no tokens): unless `--skip-pipeline` was passed, run `python run_pipeline.py` (add `--date` if given). It can take 30-60 minutes on the full market; run it in the background and wait for it to finish. If it fails, show the last 20 log lines and stop.
2. Read `data/runs/<date>/finalists.md` (it's compact). If there are no finalists, report the funnel counts and stop.
3. **consensus-checker**: one agent, give it the run folder.
4. **catalyst-researcher**: split the finalists into batches of 5 and launch all batches in parallel. Give each the run folder and its tickers.
5. **sentiment-analyst**: only if `data/runs/<date>/x/` has .jsonl files. Pass the run folder and the `x_posts_prev` values from finalists.csv. Can run in parallel with step 4.
6. **red-team**: one agent, after 3-5 finish.
7. **report-writer**: one agent, last.
8. Reply with: the report path, Keep/Watch/Cut counts, and the top 5 names in one line each (symbol, adjusted upside, one-line thesis). Nothing else.

Standing rules apply (see CLAUDE.md): EZPW is never an idea; no buy/sell instructions; one risk note at the end.
