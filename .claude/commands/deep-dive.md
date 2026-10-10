---
description: Full single-stock analysis on one ticker (standard + catalyst research + bear case)
argument-hint: "TICKER"
---

Deep dive on $ARGUMENTS.

If the ticker is EZPW: analysis only (quote with after-hours spread, FCFS comparison, gold GCUSD vs 50/200-day, recent 8-Ks, news); no buy/sell view.

Otherwise:
1. Required standard: forward P/E, PEG, analyst consensus target with implied upside, analyst count (B/H/S). Cross-check targets across Robinhood, FMP and TipRanks where available; say which source each number came from.
2. Launch **catalyst-researcher** with the ticker (use `data/runs/<latest>/` as the run folder if the ticker is there; otherwise give it `data/adhoc/`).
3. Then launch **red-team** on that one research file.
4. Reply with a compact summary: the standard metrics, why it's cheap, catalysts with dates, the strongest bear point, and the red-team verdict. Disclaimer once at the end.
