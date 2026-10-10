"""Optional cross-check of finalists against FMP (stable API).

Your FMP plan blocks analyst endpoints for many symbols ("requires a higher plan").
Blocked symbols are remembered in data/fmp_gated.json and never retried.
"""
from __future__ import annotations

import os

import pandas as pd
import requests

from .common import DATA, log, read_json, write_json

BASE = "https://financialmodelingprep.com/stable"
GATED_FILE = DATA / "fmp_gated.json"


def _get(endpoint: str, symbol: str, key: str):
    r = requests.get(f"{BASE}/{endpoint}", params={"symbol": symbol, "apikey": key}, timeout=20)
    text = r.text.lower()
    if r.status_code in (402, 403) or "higher plan" in text or "special endpoint" in text:
        return "gated"
    r.raise_for_status()
    data = r.json()
    return data[0] if isinstance(data, list) and data else None


def cross_check(symbols: list[str]) -> pd.DataFrame:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        log.info("FMP: no FMP_API_KEY, skipping cross-check")
        return pd.DataFrame()
    gated = set(read_json(GATED_FILE, []))
    rows = []
    for s in symbols:
        if s in gated:
            rows.append({"symbol": s, "fmp_status": "plan-gated"})
            continue
        try:
            cons = _get("price-target-consensus", s, key)
            summ = _get("price-target-summary", s, key)
        except Exception as e:
            rows.append({"symbol": s, "fmp_status": f"error: {str(e)[:80]}"})
            continue
        if "gated" in (cons, summ):
            gated.add(s)
            rows.append({"symbol": s, "fmp_status": "plan-gated"})
            continue
        cons, summ = cons or {}, summ or {}
        rows.append({
            "symbol": s, "fmp_status": "ok",
            "fmp_target_consensus": cons.get("targetConsensus"),
            "fmp_target_median": cons.get("targetMedian"),
            "fmp_lastq_avg": summ.get("lastQuarterAvgPriceTarget"),
            "fmp_lastq_count": summ.get("lastQuarterCount"),
            "fmp_lastm_count": summ.get("lastMonthCount"),
        })
    write_json(GATED_FILE, sorted(gated))
    ok = sum(r["fmp_status"] == "ok" for r in rows)
    log.info("FMP: %d of %d finalists cross-checked (%d plan-gated)", ok, len(rows),
             sum(r["fmp_status"] == "plan-gated" for r in rows))
    return pd.DataFrame(rows)
