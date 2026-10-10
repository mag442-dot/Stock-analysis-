#!/usr/bin/env python3
"""Stock Scout data pipeline. Uses no Claude tokens.

    python run_pipeline.py                 # full run for today
    python run_pipeline.py --limit 300     # quick test on the first 300 listings
    python run_pipeline.py --from score    # re-score from cached data (after editing config.yaml)

Stages: universe -> prices -> snapshots -> deep -> score -> crosscheck -> x -> report
Every stage writes a CSV under data/runs/<date>/, so later stages can be re-run alone.
"""
from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from scout import analysts, fmp, history, prices, scoring, universe, x_posts
from scout.common import load_config, load_env, log, run_dir, setup_logging

STAGES = ["universe", "prices", "snapshots", "deep", "score", "crosscheck", "x", "report"]


def _pct(x):
    return "" if pd.isna(x) else f"{x:+.0%}"


def _s(x):
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


def _num(x, fmt="{:.1f}"):
    return "" if pd.isna(x) else fmt.format(x)


def write_finalists_md(fin: pd.DataFrame, path, run_date: str, counts: dict) -> None:
    lines = [
        f"# Stock Scout finalists — {run_date}",
        "",
        "Funnel: " + " → ".join(f"{k} {v:,}" for k, v in counts.items()),
        "",
        "Adjusted = upside × Buy share × depth × age × event; rank = adjusted × revision multiplier.",
        "",
        "| # | Symbol | Name | Sector | Price → Target | Upside / Adj | Analysts (B/H/S) | Fwd P/E | PEG | EPS rev 30d | Target ↑/↓ 60d | Signal | Verdict | Next earnings | Prior runs | Flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(fin.to_dict("records"), 1):
        bhs = f"{int(r.get('n_analysts') or 0)} ({int(r.get('buys') or 0)}/{int(r.get('holds') or 0)}/{int(r.get('sells') or 0)})"
        fmp_note = ""
        if r.get("fmp_status") == "ok" and not pd.isna(r.get("fmp_target_consensus")):
            fmp_note = f"; FMP cons ${r['fmp_target_consensus']:.2f}"
        elif _s(r.get("fmp_status")):
            fmp_note = f"; FMP {r['fmp_status']}"
        lines.append(
            f"| {i} | {r['symbol']} | {_s(r.get('name'))[:28]} | {_s(r.get('sector'))} | "
            f"${r['price']:.2f} → ${r['target_used']:.2f} | {_pct(r['upside'])} / {_pct(r['adj_upside'])} | "
            f"{bhs} | {_num(r.get('forward_pe'))} | {_num(r.get('peg'), '{:.2f}')} | {_pct(r.get('eps_rev_30d'))} | "
            f"{int(r.get('target_raises') or 0)}/{int(r.get('target_cuts') or 0)} | {r['revision_signal']} | {r['verdict']} | "
            f"{_s(r.get('next_earnings'))} | {int(r.get('prior_runs_listed') or 0)} | {_s(r.get('flags')) + fmp_note} |"
        )
    lines += ["", "Data: Yahoo Finance via yfinance (consensus, notes, EPS trend), prices as of each row's last close."]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=date.today().isoformat(), help="run folder date (YYYY-MM-DD)")
    ap.add_argument("--from", dest="start", choices=STAGES, default="universe")
    ap.add_argument("--limit", type=int, help="only the first N listings (testing)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    load_env()
    cfg = load_config()
    rd = run_dir(args.date)
    asof = date.fromisoformat(args.date)
    sleep = cfg["rate_limit"]["info_sleep_seconds"]
    go = lambda s: STAGES.index(s) >= STAGES.index(args.start)  # noqa: E731
    f = lambda name: rd / f"{name}.csv"  # noqa: E731

    if go("universe"):
        uni = universe.build_universe(cfg)
        if args.limit:
            uni = uni.head(args.limit)
        uni.to_csv(f("universe"), index=False)
    uni = pd.read_csv(f("universe"))

    if go("prices"):
        px = prices.download_prices(uni["yahoo"].tolist(), cfg["rate_limit"]["price_batch_size"])
        px.to_csv(f("prices"), index=False)
        pf = prices.prefilter(px, cfg).merge(uni, on="yahoo", how="left")
        pf.to_csv(f("prefiltered"), index=False)
    pf = pd.read_csv(f("prefiltered"))

    if go("snapshots"):
        snap = analysts.fetch_snapshots(pf["yahoo"].tolist(), sleep, args.date)
        snap = pf.merge(snap.drop(columns=["name"], errors="ignore"), on="yahoo", how="left")
        snap.to_csv(f("snapshots"), index=False)
        screened = analysts.screen_snapshots(snap, cfg)
        screened.to_csv(f("screened"), index=False)
    screened = pd.read_csv(f("screened"))

    if go("deep"):
        deep = analysts.fetch_deep(screened["yahoo"].tolist(), cfg, sleep, args.date)
        if "fresh_targets" in deep:
            deep["fresh_targets"] = deep["fresh_targets"].apply(
                lambda v: ",".join(map(str, v)) if isinstance(v, list) else "")
        deep.to_csv(f("deep"), index=False)
    deep = pd.read_csv(f("deep"))

    if go("score"):
        merged = screened.merge(deep, on="yahoo", how="left")
        if "fresh_targets" in merged:
            merged["fresh_targets"] = merged["fresh_targets"].apply(
                lambda v: [float(x) for x in str(v).split(",") if x not in ("", "nan")])
        scored = scoring.score_frame(merged, cfg, asof)
        scored.to_csv(f("scored"), index=False)
        fin = scoring.pick_finalists(scored, cfg)
        fin = history.add_history_columns(fin, args.date)
        fin.to_csv(f("finalists"), index=False)
    scored = pd.read_csv(f("scored"))
    fin = pd.read_csv(f("finalists"))

    if go("crosscheck") and cfg.get("fmp", {}).get("enabled"):
        fx = fmp.cross_check(fin["symbol"].tolist())
        if not fx.empty:
            fin = fin.drop(columns=[c for c in fx.columns if c != "symbol" and c in fin], errors="ignore")
            fin = fin.merge(fx, on="symbol", how="left")
            fin.to_csv(f("finalists"), index=False)

    if go("x"):
        counts = x_posts.fetch_posts(fin["symbol"].tolist(), cfg, args.date)
        if counts:
            fin["x_posts"] = fin["symbol"].map(counts)
            fin.to_csv(f("finalists"), index=False)

    if go("report"):
        if "x_posts" in fin:
            scored["x_posts"] = scored["symbol"].map(fin.set_index("symbol")["x_posts"])
        history.save(scored, args.date)
        counts = {
            "listings": len(uni),
            "liquid + dislocated": len(pf),
            "screened": len(screened),
            "scored": int(scored["verdict"].isin(["Opportunity", "Watch", "Falling knife"]).sum()),
            "finalists": len(fin),
        }
        write_finalists_md(fin, rd / "finalists.md", args.date, counts)
        vc = scored["verdict"].value_counts().to_dict()
        log.info("Done. Verdicts: %s", vc)
        log.info("Finalists table: %s", rd / "finalists.md")


if __name__ == "__main__":
    main()
