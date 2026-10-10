"""Optional: recent X posts for finalists (official API, pay-per-use, last 7 days only).

Writes data/runs/<date>/x/<SYMBOL>.jsonl with trimmed fields for the sentiment agent.
A cost estimate is checked against x.max_cost_usd before any call is made.
"""
from __future__ import annotations

import json
import os

import requests

from .common import log, run_dir

SEARCH = "https://api.x.com/2/tweets/search/recent"


def estimate_cost(n_tickers: int, xcfg: dict) -> float:
    per_post = xcfg["cost_per_post"] + (xcfg["cost_per_user"] if xcfg["expand_authors"] else 0)
    return n_tickers * xcfg["posts_per_ticker"] * per_post


def fetch_posts(symbols: list[str], cfg: dict, run_date: str) -> dict:
    xcfg = cfg["x"]
    token = os.environ.get("X_BEARER_TOKEN")
    if not xcfg.get("enabled"):
        log.info("X: disabled in config")
        return {}
    if not token:
        log.info("X: no X_BEARER_TOKEN, skipping")
        return {}
    est = estimate_cost(len(symbols), xcfg)
    if est > xcfg["max_cost_usd"]:
        keep = int(xcfg["max_cost_usd"] / estimate_cost(1, xcfg))
        log.warning("X: estimated $%.2f exceeds cap $%.2f; limiting to top %d names",
                    est, xcfg["max_cost_usd"], keep)
        symbols = symbols[:keep]
    out_dir = run_dir(run_date) / "x"
    out_dir.mkdir(exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    counts = {}
    for sym in symbols:
        params = {
            "query": f"${sym} lang:en -is:retweet",
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,author_id",
        }
        if xcfg["expand_authors"]:
            params.update({"expansions": "author_id",
                           "user.fields": "public_metrics,created_at,verified"})
        posts, users, nxt = [], {}, None
        while len(posts) < xcfg["posts_per_ticker"]:
            if nxt:
                params["next_token"] = nxt
            r = requests.get(SEARCH, headers=headers, params=params, timeout=30)
            if r.status_code == 429:
                log.warning("X: rate limited on %s, moving on", sym)
                break
            if r.status_code != 200:
                log.warning("X: %s -> HTTP %s %s", sym, r.status_code, r.text[:120])
                break
            body = r.json()
            posts += body.get("data", [])
            for u in body.get("includes", {}).get("users", []):
                users[u["id"]] = u
            nxt = body.get("meta", {}).get("next_token")
            if not nxt:
                break
        with open(out_dir / f"{sym}.jsonl", "w") as f:
            for p in posts[: xcfg["posts_per_ticker"]]:
                u = users.get(p.get("author_id"), {})
                m = p.get("public_metrics", {})
                f.write(json.dumps({
                    "t": p.get("created_at"), "text": p.get("text", "")[:400],
                    "likes": m.get("like_count"), "reposts": m.get("retweet_count"),
                    "followers": u.get("public_metrics", {}).get("followers_count"),
                    "acct_created": u.get("created_at"), "verified": u.get("verified"),
                }) + "\n")
        counts[sym] = min(len(posts), xcfg["posts_per_ticker"])
    log.info("X: fetched posts for %d names (%d posts)", len(counts), sum(counts.values()))
    return counts
