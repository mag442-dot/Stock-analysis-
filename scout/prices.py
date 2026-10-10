"""Stage 1: bulk 1-year price history for the whole universe, then a cheap prefilter."""
from __future__ import annotations

import time

import pandas as pd

from .common import log


def price_metrics(close: pd.Series, volume: pd.Series) -> dict | None:
    """Metrics from one ticker's daily closes and volumes (oldest first)."""
    close = close.dropna()
    if len(close) < 60:
        return None
    volume = volume.reindex(close.index).fillna(0)
    last = float(close.iloc[-1])
    high_52w = float(close.max())
    sma200 = float(close.tail(200).mean()) if len(close) >= 150 else None
    dollar_vol = float((close.tail(20) * volume.tail(20)).mean())
    chg_60d = float(last / close.iloc[-61] - 1) if len(close) > 61 else None
    return {
        "price": last,
        "price_date": close.index[-1].date().isoformat(),
        "high_52w": high_52w,
        "drawdown_52w": 1 - last / high_52w if high_52w else None,
        "sma200": sma200,
        "below_sma200": (last < sma200) if sma200 else None,
        "avg_dollar_volume": dollar_vol,
        "chg_60d": chg_60d,
    }


def download_prices(tickers: list[str], batch_size: int = 200) -> pd.DataFrame:
    import yfinance as yf

    rows = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        log.info("Prices: batch %d-%d of %d", i + 1, i + len(batch), len(tickers))
        for attempt in range(3):
            try:
                data = yf.download(
                    batch, period="1y", interval="1d", auto_adjust=True,
                    group_by="ticker", threads=True, progress=False,
                )
                break
            except Exception as e:  # network hiccup or throttling
                log.warning("Price batch failed (%s), retrying", e)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                sub = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                m = price_metrics(sub["Close"], sub["Volume"])
            except KeyError:
                m = None
            if m:
                rows.append({"yahoo": t, **m})
    return pd.DataFrame(rows)


def prefilter(prices: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    p = cfg["prefilter"]
    df = prices[(prices["price"] >= p["min_price"]) &
                (prices["avg_dollar_volume"] >= p["min_avg_dollar_volume"])]
    dd = p.get("min_drawdown_from_52w_high")
    below = p.get("keep_if_below_200d_sma")
    if dd or below:
        cond = pd.Series(False, index=df.index)
        if dd:
            cond |= df["drawdown_52w"] >= dd
        if below:
            cond |= df["below_sma200"].fillna(False).astype(bool)
        df = df[cond]
    log.info("Prefilter: %d of %d pass liquidity + dislocation", len(df), len(prices))
    return df.reset_index(drop=True)
