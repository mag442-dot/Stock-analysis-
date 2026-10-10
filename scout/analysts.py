"""Stages 2-3: analyst consensus, rating split, dated notes, EPS revisions, earnings dates.

Source: Yahoo Finance via yfinance (free, whole market, unofficial and occasionally
flaky). Every per-ticker result is cached under data/runs/<date>/cache/ so an
interrupted run resumes where it stopped.
"""
from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd

from .common import cache_dir, log, read_json, write_json

INFO_FIELDS = {
    "shortName": "name", "sector": "sector", "industry": "industry",
    "marketCap": "market_cap", "forwardPE": "forward_pe", "trailingPE": "trailing_pe",
    "trailingPegRatio": "peg", "targetMeanPrice": "target_mean",
    "targetMedianPrice": "target_median", "targetHighPrice": "target_high",
    "targetLowPrice": "target_low", "numberOfAnalystOpinions": "n_analysts",
    "recommendationMean": "rec_mean", "currentPrice": "info_price",
    "quoteType": "quote_type",
}


# ---------- parsing (pure, unit-tested) ----------

def parse_info(info: dict) -> dict:
    out = {dst: info.get(src) for src, dst in INFO_FIELDS.items()}
    if out.get("peg") is None:
        out["peg"] = info.get("pegRatio")
    return out


def parse_recommendations(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    row = df[df["period"] == "0m"].iloc[0] if "period" in df else df.iloc[0]
    g = lambda k: int(row.get(k, 0) or 0)  # noqa: E731
    return {"buys": g("strongBuy") + g("buy"), "holds": g("hold"),
            "sells": g("sell") + g("strongSell")}


def parse_notes(df: pd.DataFrame | None, asof: date, fresh_days: int, rev_days: int) -> dict:
    """Dated firm-level notes -> newest note date, fresh per-firm targets, raises/cuts."""
    if df is None or df.empty:
        return {}
    d = df.copy()
    idx = pd.to_datetime(d.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    d["date"] = idx
    d = d.dropna(subset=["date"]).sort_values("date")
    asof_ts = pd.Timestamp(asof)
    age = (asof_ts - d["date"]).dt.days
    out = {"newest_note": d["date"].iloc[-1].date().isoformat() if len(d) else None}

    if "currentPriceTarget" in d:
        recent = d[(age <= fresh_days) & (d["currentPriceTarget"].fillna(0) > 0)]
        latest_per_firm = recent.groupby("Firm").tail(1)
        out["fresh_targets"] = [round(float(x), 2) for x in latest_per_firm["currentPriceTarget"]]

    win = d[age <= rev_days]
    raises = cuts = 0
    if "priceTargetAction" in win:
        act = win["priceTargetAction"].fillna("").str.lower()
        raises += int(act.str.startswith("raise").sum())
        cuts += int(act.str.startswith("lower").sum())
    elif {"currentPriceTarget", "priorPriceTarget"} <= set(win.columns):
        cur, pri = win["currentPriceTarget"], win["priorPriceTarget"]
        raises += int(((cur > pri) & (pri > 0)).sum())
        cuts += int(((cur < pri) & (pri > 0)).sum())
    if "Action" in win:
        a = win["Action"].fillna("").str.lower()
        out["upgrades"] = int((a == "up").sum())
        out["downgrades"] = int((a == "down").sum())
    out["target_raises"], out["target_cuts"] = raises, cuts
    return out


def parse_eps_trend(df: pd.DataFrame | None) -> dict:
    """Next-fiscal-year EPS estimate now vs 30 and 90 days ago."""
    if df is None or df.empty:
        return {}
    for period in ("+1y", "0y"):
        if period in df.index:
            r = df.loc[period]
            return {"eps_period": period, "eps_now": _f(r.get("current")),
                    "eps_30d": _f(r.get("30daysAgo")), "eps_90d": _f(r.get("90daysAgo"))}
    return {}


def parse_earnings_dates(df: pd.DataFrame | None, asof: date) -> dict:
    if df is None or df.empty:
        return {}
    idx = pd.to_datetime(df.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    days = pd.Series(idx.normalize(), index=df.index)
    asof_ts = pd.Timestamp(asof)
    past = days[days <= asof_ts]
    fut = days[days > asof_ts]
    return {"last_earnings": past.max().date().isoformat() if len(past) else None,
            "next_earnings": fut.min().date().isoformat() if len(fut) else None}


def _f(x):
    try:
        x = float(x)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


# ---------- fetching ----------

def fetch_snapshots(tickers: list[str], sleep: float, run_date: str) -> pd.DataFrame:
    import yfinance as yf

    cdir = cache_dir("info", run_date)
    rows = []
    for i, t in enumerate(tickers, 1):
        path = cdir / f"{t}.json"
        rec = read_json(path)
        if rec is None:
            try:
                rec = parse_info(yf.Ticker(t).info or {})
            except Exception as e:
                log.debug("info failed %s: %s", t, e)
                rec = {"error": str(e)[:200]}
            write_json(path, rec)
            time.sleep(sleep)
        if i % 100 == 0:
            log.info("Snapshots: %d / %d", i, len(tickers))
        rows.append({"yahoo": t, **rec})
    return pd.DataFrame(rows)


def fetch_deep(tickers: list[str], cfg: dict, sleep: float, run_date: str) -> pd.DataFrame:
    import yfinance as yf

    sc = cfg["scoring"]
    asof = datetime.fromisoformat(run_date).date()
    cdir = cache_dir("deep", run_date)
    rows = []
    for i, t in enumerate(tickers, 1):
        path = cdir / f"{t}.json"
        rec = read_json(path)
        if rec is None:
            rec = {}
            tk = yf.Ticker(t)
            for label, fn in (
                ("rec", lambda: parse_recommendations(tk.recommendations)),
                ("notes", lambda: parse_notes(tk.upgrades_downgrades, asof,
                                              sc["fresh_window_days"], sc["revision_window_days"])),
                ("eps", lambda: parse_eps_trend(tk.eps_trend)),
                ("earn", lambda: parse_earnings_dates(tk.get_earnings_dates(limit=12), asof)),
            ):
                try:
                    rec.update(fn())
                except Exception as e:
                    rec.setdefault("errors", []).append(f"{label}: {str(e)[:120]}")
            write_json(path, rec)
            time.sleep(sleep)
        if i % 25 == 0:
            log.info("Deep data: %d / %d", i, len(tickers))
        rows.append({"yahoo": t, **rec})
    return pd.DataFrame(rows)


def screen_snapshots(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    s = cfg["screen"]
    d = df.copy()
    for c in ("market_cap", "forward_pe", "n_analysts", "target_mean", "price"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d["raw_upside"] = d["target_mean"] / d["price"] - 1
    mask = (d["market_cap"] >= s["min_market_cap"]) & (d["n_analysts"] >= s["min_analysts"])
    if s.get("require_positive_forward_pe"):
        mask &= d["forward_pe"] > 0
    if s.get("max_forward_pe"):
        mask &= d["forward_pe"] <= s["max_forward_pe"]
    mask &= d["raw_upside"] >= s["min_raw_upside"]
    if "quote_type" in d:
        mask &= d["quote_type"].fillna("EQUITY") == "EQUITY"
    out = d[mask].sort_values("raw_upside", ascending=False)
    log.info("Screen: %d of %d pass size, coverage, valuation and upside", len(out), len(d))
    return out.reset_index(drop=True)
