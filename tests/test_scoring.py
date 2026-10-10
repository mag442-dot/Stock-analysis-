"""Offline tests: scoring math and parsers on synthetic data (no network)."""
from datetime import date

import pandas as pd
import pytest

from scout import analysts, prices, scoring
from scout.common import load_config

CFG = load_config()
ASOF = date(2026, 10, 9)


def base_row(**kw):
    r = {"symbol": "TEST", "price": 50.0, "target_mean": 75.0, "target_median": 74.0,
         "n_analysts": 20, "buys": 15, "holds": 4, "sells": 1,
         "newest_note": "2026-09-25", "last_earnings": "2026-08-05", "next_earnings": "2026-11-05",
         "eps_now": 4.20, "eps_30d": 4.00, "target_raises": 4, "target_cuts": 1, "chg_60d": -0.10,
         "fresh_targets": []}
    r.update(kw)
    return r


def test_adjusted_upside_formula():
    s = scoring.score_row(base_row(), CFG, ASOF)
    # 50% upside x 0.75 buy share x 0.85 depth x 1.0 age x 1.0 event
    assert s["upside"] == pytest.approx(0.50)
    assert s["adj_upside"] == pytest.approx(0.50 * 0.75 * 0.85, abs=1e-4)
    assert s["revision_signal"] == "confirming"
    assert s["verdict"] == "Opportunity"
    assert s["rank_score"] == pytest.approx(s["adj_upside"] * 1.15, abs=1e-4)


def test_falling_knife_on_eps_cuts():
    s = scoring.score_row(base_row(eps_now=3.50, eps_30d=4.00), CFG, ASOF)
    assert s["revision_signal"] == "falling knife"
    assert s["verdict"] == "Falling knife"


def test_falling_knife_on_target_cuts():
    s = scoring.score_row(base_row(target_raises=0, target_cuts=5), CFG, ASOF)
    assert s["verdict"] == "Falling knife"


def test_event_haircut_and_age():
    s = scoring.score_row(base_row(newest_note="2026-06-01", last_earnings="2026-08-05"), CFG, ASOF)
    assert s["event_f"] == 0.85
    assert s["note_age_days"] == 130
    assert s["age_f"] == 0.60  # over 120 days


def test_fresh_targets_override_stale_consensus():
    s = scoring.score_row(base_row(fresh_targets=[60.0, 62.0, 58.0]), CFG, ASOF)
    assert s["target_used"] == 60.0
    assert "using fresh" in s["flags"]


def test_depth_and_age_tables():
    sc = CFG["scoring"]
    assert scoring.depth_factor(35, sc["depth_factors"]) == 1.0
    assert scoring.depth_factor(12, sc["depth_factors"]) == 0.7
    assert scoring.depth_factor(3, sc["depth_factors"]) == 0.5
    assert scoring.age_factor(10, sc["age_factors"]) == 1.0
    assert scoring.age_factor(75, sc["age_factors"]) == 0.85
    assert scoring.age_factor(500, sc["age_factors"]) == 0.6
    assert scoring.age_factor(None, sc["age_factors"]) == 1.0


def test_parse_notes_and_eps():
    idx = pd.to_datetime(["2026-09-30", "2026-09-10", "2026-08-20", "2026-03-01"])
    df = pd.DataFrame({
        "Firm": ["A", "B", "A", "C"], "Action": ["up", "main", "main", "down"],
        "priceTargetAction": ["Raises", "Lowers", "Raises", "Lowers"],
        "currentPriceTarget": [80, 70, 75, 40], "priorPriceTarget": [75, 72, 70, 50],
    }, index=idx)
    out = analysts.parse_notes(df, ASOF, fresh_days=90, rev_days=60)
    assert out["newest_note"] == "2026-09-30"
    assert sorted(out["fresh_targets"]) == [70.0, 80.0]  # latest per firm, C too old
    assert out["target_raises"] == 2 and out["target_cuts"] == 1
    eps = pd.DataFrame({"current": [4.2], "30daysAgo": [4.0], "90daysAgo": [3.9]}, index=["+1y"])
    assert analysts.parse_eps_trend(eps)["eps_now"] == 4.2


def test_price_metrics_and_prefilter():
    idx = pd.bdate_range(end="2026-10-09", periods=250)
    close = pd.Series([100 - i * 0.2 for i in range(250)], index=idx)  # steady decline
    vol = pd.Series(1_000_000, index=idx)
    m = prices.price_metrics(close, vol)
    assert m["drawdown_52w"] == pytest.approx(1 - close.iloc[-1] / 100)
    assert m["below_sma200"] is True
    df = pd.DataFrame([{"yahoo": "TEST", **m}])
    assert len(prices.prefilter(df, CFG)) == 1


def test_finalists_order():
    rows = [base_row(symbol="AAA"), base_row(symbol="BBB", eps_now=4.0, eps_30d=4.0),
            base_row(symbol="CCC", eps_now=3.0, eps_30d=4.0)]
    scored = scoring.score_frame(pd.DataFrame(rows), CFG, ASOF)
    fin = scoring.pick_finalists(scored, CFG)
    assert list(fin["symbol"]) == ["AAA", "BBB"]  # Opportunity, then Watch; knife excluded
