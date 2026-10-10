"""Stage 4: adjusted upside (portfolio-analyst-potential method) + revision signal + verdict.

Adjusted = upside x Buy share x depth x age x event
Rank = Adjusted x revision multiplier (confirming / neutral / falling knife)
This is a heuristic for ordering research, not a valuation model.
"""
from __future__ import annotations

from datetime import date
from statistics import median

import pandas as pd


def _num(x):
    try:
        x = float(x)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _txt(x):
    """CSV round-trips turn missing strings into NaN (truthy); normalise to None."""
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else x


def depth_factor(n: float | None, table: list) -> float:
    n = n or 0
    for threshold, factor in sorted(table, key=lambda r: -r[0]):
        if n >= threshold:
            return factor
    return table[-1][1]


def age_factor(days: int | None, table: list) -> float:
    if days is None:
        return 1.0  # undated: no haircut, but flagged
    for threshold, factor in sorted(table, key=lambda r: r[0]):
        if days <= threshold:
            return factor
    return sorted(table, key=lambda r: r[0])[-1][1]


def _days(asof: date, iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (asof - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return None


def score_row(r: dict, cfg: dict, asof: date) -> dict:
    sc = cfg["scoring"]
    flags: list[str] = []
    price = _num(r.get("price"))
    target = _num(r.get("target_mean"))
    if not price or not target:
        return {"verdict": "No data", "flags": "missing price or target"}

    # Cross-check: fresh per-firm targets vs the consensus mean.
    target_used, basis = target, "consensus"
    fresh = r.get("fresh_targets") or []
    if isinstance(fresh, list) and len(fresh) >= sc["fresh_min_firms"]:
        f = median(fresh)
        if abs(f / target - 1) > sc["fresh_divergence"]:
            target_used, basis = f, f"fresh median of {len(fresh)} firms"
            flags.append(f"consensus ${target:.2f} vs fresh ${f:.2f}: using fresh")
    upside = target_used / price - 1

    # Outlier check: mean vs median.
    med = _num(r.get("target_median"))
    if med and abs(target / med - 1) > 0.10:
        flags.append(f"mean ${target:.2f} vs median ${med:.2f} (outlier likely)")

    buys, holds, sells = (int(_num(r.get(k)) or 0) for k in ("buys", "holds", "sells"))
    total = buys + holds + sells
    buy_share = buys / total if total else None
    if buy_share is None:
        flags.append("no rating split")

    n = _num(r.get("n_analysts"))
    depth = depth_factor(n, sc["depth_factors"])
    note_age = _days(asof, _txt(r.get("newest_note")))
    age = age_factor(note_age, sc["age_factors"])
    if note_age is None:
        flags.append("undated targets")

    event = 1.0
    last_earn = _txt(r.get("last_earnings"))
    newest = _txt(r.get("newest_note"))
    if last_earn and newest and str(newest)[:10] < str(last_earn)[:10]:
        event = sc["event_haircut"]
        flags.append("targets predate last earnings")

    adjusted = upside * (buy_share if buy_share is not None else 0.5) * depth * age * event

    # Revision signal.
    eps_now, eps_30 = _num(r.get("eps_now")), _num(r.get("eps_30d"))
    eps_rev = (eps_now / eps_30 - 1) if (eps_now and eps_30 and eps_30 > 0) else None
    raises, cuts = int(_num(r.get("target_raises")) or 0), int(_num(r.get("target_cuts")) or 0)
    net_rev = (raises - cuts) / (raises + cuts) if (raises + cuts) else 0.0

    knife = ((eps_rev is not None and eps_rev <= sc["falling_knife_eps_cut"]) or
             (raises + cuts >= 3 and net_rev <= sc["falling_knife_net_revisions"]))
    confirming = (eps_rev is not None and eps_rev > 0) and raises >= cuts and not knife
    if knife:
        signal, mult = "falling knife", sc["multipliers"]["falling_knife"]
    elif confirming:
        signal, mult = "confirming", sc["multipliers"]["confirming"]
    else:
        signal, mult = "neutral", sc["multipliers"]["neutral"]

    chg = _num(r.get("chg_60d"))
    if chg is not None and chg <= -sc["stale_price_drop"]:
        flags.append(f"price {chg:+.0%} in 60d: targets may be stale")

    nd = _days(asof, _txt(r.get("next_earnings")))
    days_to = -nd if nd is not None else None
    if days_to is not None and 0 <= days_to <= cfg["finalists"]["earnings_soon_days"]:
        flags.append("reports within 14d: targets about to reset")

    if knife:
        verdict = "Falling knife"
    elif adjusted >= cfg["finalists"]["min_adjusted_upside"] and signal == "confirming":
        verdict = "Opportunity"
    elif adjusted >= cfg["finalists"]["min_adjusted_upside"]:
        verdict = "Watch"
    else:
        verdict = "Below bar"

    return {
        "target_used": round(target_used, 2), "target_basis": basis,
        "upside": round(upside, 4), "buy_share": None if buy_share is None else round(buy_share, 3),
        "depth_f": depth, "age_f": age, "event_f": event, "note_age_days": note_age,
        "adj_upside": round(adjusted, 4), "eps_rev_30d": None if eps_rev is None else round(eps_rev, 4),
        "target_raises": raises, "target_cuts": cuts, "revision_signal": signal,
        "rank_score": round(adjusted * mult, 4), "verdict": verdict,
        "days_to_earnings": days_to, "flags": "; ".join(flags),
    }


def score_frame(df: pd.DataFrame, cfg: dict, asof: date) -> pd.DataFrame:
    scored = [score_row(r, cfg, asof) for r in df.to_dict("records")]
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(scored)], axis=1)
    return out.sort_values("rank_score", ascending=False, na_position="last").reset_index(drop=True)


def pick_finalists(scored: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    n = cfg["finalists"]["count"]
    order = {"Opportunity": 0, "Watch": 1}
    pool = scored[scored["verdict"].isin(order)].copy()
    pool["_o"] = pool["verdict"].map(order)
    return pool.sort_values(["_o", "rank_score"], ascending=[True, False]).head(n).drop(columns="_o")
