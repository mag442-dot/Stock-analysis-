"""Weekly snapshots in SQLite so the agents can see persistence and trend across runs."""
from __future__ import annotations

import sqlite3

import pandas as pd

from .common import DATA

DB = DATA / "history.sqlite"
COLS = ["run_date", "symbol", "price", "target_used", "adj_upside", "rank_score",
        "eps_rev_30d", "revision_signal", "verdict", "x_posts"]


def _conn():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (run_date TEXT, symbol TEXT, price REAL, "
        "target_used REAL, adj_upside REAL, rank_score REAL, eps_rev_30d REAL, "
        "revision_signal TEXT, verdict TEXT, x_posts INTEGER, PRIMARY KEY (run_date, symbol))"
    )
    return c


def save(scored: pd.DataFrame, run_date: str) -> None:
    d = scored.copy()
    d["run_date"] = run_date
    if "x_posts" not in d:
        d["x_posts"] = None
    d = d[d["verdict"].isin(["Opportunity", "Watch", "Falling knife"])]
    with _conn() as c:
        c.execute("DELETE FROM snapshots WHERE run_date = ?", (run_date,))
        d[COLS].to_sql("snapshots", c, if_exists="append", index=False)


def add_history_columns(df: pd.DataFrame, run_date: str) -> pd.DataFrame:
    """Weeks on list (prior runs as Opportunity/Watch) and change in adjusted upside vs last run."""
    with _conn() as c:
        prior = pd.read_sql(
            "SELECT * FROM snapshots WHERE run_date < ? ORDER BY run_date", c, params=(run_date,)
        )
    if prior.empty:
        df["prior_runs_listed"] = 0
        df["adj_upside_prev"] = None
        df["x_posts_prev"] = None
        return df
    listed = prior[prior["verdict"].isin(["Opportunity", "Watch"])].groupby("symbol").size()
    last = prior.sort_values("run_date").groupby("symbol").tail(1).set_index("symbol")
    df["prior_runs_listed"] = df["symbol"].map(listed).fillna(0).astype(int)
    df["adj_upside_prev"] = df["symbol"].map(last["adj_upside"])
    df["x_posts_prev"] = df["symbol"].map(last["x_posts"])
    return df
