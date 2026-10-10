# Stock Scout

Weekly market-wide scan for US stocks trading far below analyst price targets, then an agent review that separates real mispricings from stale targets and value traps.

## How it's split (to save Claude usage)
- `run_pipeline.py` + `scout/` do all data collection and scoring in Python. **No tokens.** Output lands in `data/runs/<date>/`.
- Agents in `.claude/agents/` only do judgment work on the 25 finalists.
- `/scout` runs a full cycle; `/deep-dive TICKER` analyzes one name.

## Pipeline funnel
universe (Nasdaq Trader files, ~6k listings) → prices + liquidity/dislocation prefilter (bulk download) → per-ticker snapshot screen (market cap, coverage, forward P/E, raw upside) → deep data (rating split, dated notes, EPS trend, earnings dates) → scoring → finalists → optional FMP cross-check and X posts → `finalists.md`.

Thresholds live in `config.yaml`. After changing scoring settings, re-score from cache with `python run_pipeline.py --from score`.

## Scoring (same method as the portfolio-analyst-potential skill)
Adjusted upside = upside × Buy share × depth × age × event.
- Depth: 30+ analysts 1.0; 15-29 0.85; 10-14 0.7; under 10 0.5.
- Age (days since newest dated note): ≤30 1.0; ≤60 0.95; ≤90 0.85; ≤120 0.75; older 0.6.
- Event: ×0.85 if targets predate the last earnings report.
- Fresh-target cross-check: if the median of the latest per-firm targets (90 days, 3+ firms) differs from consensus by >10%, use it.
Rank = adjusted × revision multiplier: confirming 1.15 (EPS estimates up, raises ≥ cuts), neutral 1.0, falling knife 0.6 (EPS cut ≥3% or cuts clearly outnumber raises).

## Standing rules
- **EZPW is never a buy or sell idea.** It's excluded from the universe. If asked about it, analysis only.
- Every stock analysis includes forward P/E, PEG (where available) and consensus target with implied upside.
- Cross-check analyst data across sources; say which number came from where; write "unverified" rather than estimate.
- Precision matters: dates, units, notional vs. profit.
- No buy/sell instructions. State risk context once, factually, at the end, not at the start.

## Context discipline
- Never `cat` a CSV. Print only the columns and rows you need (pandas one-liners).
- Agents return short summaries; details stay in files.
- FMP analyst endpoints are plan-gated for many symbols; `data/fmp_gated.json` lists them. Don't retry.
- TipRanks (via the FMP connector) shows only 2-10 firms per name and its date filter is unreliable.

## Data caveats
- Yahoo Finance via yfinance is free and covers the whole market, but it's unofficial: fields occasionally go missing or change. The pipeline caches per ticker and tolerates gaps; flags show what's missing.
- X API recent search covers the last 7 days only and bills per post read.
