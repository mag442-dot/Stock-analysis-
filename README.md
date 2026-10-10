# Stock Scout

Scans the whole US market each week for stocks trading far below analyst price targets, then has Claude Code agents decide which gaps are real and which are stale targets or value traps.

The heavy lifting (thousands of tickers) is plain Python and uses **no Claude usage**. Claude only reviews the ~25 finalists.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # 9 offline tests should pass
cp .env.example .env         # add keys (both optional)
python run_pipeline.py --limit 300   # small test run
```
Then open Claude Code in the folder and run `/scout --skip-pipeline` to try the agents on that test run.

## Weekly use
- `/scout` runs the pipeline (30-60 min for the full market) and then the agents. Report lands in `reports/<date>.md`.
- `/deep-dive NVDA` analyzes a single stock.
- Cron (Sunday 7pm): `0 19 * * 0 cd /path/to/repo && .venv/bin/python run_pipeline.py >> data/cron.log 2>&1 && claude -p "/scout --skip-pipeline"`

## The agents

| Agent | Model | Job |
|---|---|---|
| consensus-checker | Sonnet | Cross-checks targets against Robinhood and TipRanks, corrects adjusted upside |
| catalyst-researcher | Sonnet | Why it's down, are analysts reacting, what closes the gap (batches of 5, in parallel) |
| sentiment-analyst | Haiku | Scores X posts: tone, attention, red flags (only if X is enabled) |
| red-team | Opus | Bear case on every name: Keep / Watch / Cut |
| report-writer | Haiku | Assembles the weekly report |

## Tuning
Everything lives in `config.yaml`. After a change, re-score from cache: `python run_pipeline.py --from score`.

Not investment advice.
