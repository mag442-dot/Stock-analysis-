"""Stage 0: the full US-listed common-stock universe from Nasdaq Trader symbol files (free)."""
from __future__ import annotations

import io

import pandas as pd
import requests

from .common import log

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
HEADERS = {"User-Agent": "stock-scout/1.0 (personal research)"}


def _fetch(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    lines = [ln for ln in r.text.splitlines() if not ln.startswith("File Creation Time")]
    return pd.read_csv(io.StringIO("\n".join(lines)), sep="|", dtype=str)


def to_yahoo(symbol: str) -> str:
    """Class shares use a dot on the exchange (BRK.B) and a dash on Yahoo (BRK-B)."""
    return symbol.replace(".", "-")


def build_universe(cfg: dict) -> pd.DataFrame:
    ucfg = cfg["universe"]
    nas = _fetch(NASDAQ_URL)
    nas = nas.rename(columns={"Symbol": "symbol", "Security Name": "name"})
    nas["exchange"] = "NASDAQ"

    oth = _fetch(OTHER_URL)
    oth = oth.rename(columns={"ACT Symbol": "symbol", "Security Name": "name"})
    oth["exchange"] = oth["Exchange"].map(
        {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
    ).fillna(oth["Exchange"])

    cols = ["symbol", "name", "exchange", "ETF", "Test Issue"]
    df = pd.concat([nas[cols], oth[cols]], ignore_index=True).dropna(subset=["symbol"])

    df = df[df["Test Issue"] != "Y"]
    if ucfg.get("exclude_etfs", True):
        df = df[df["ETF"] != "Y"]
    # Preferreds and other special classes carry "$" or other punctuation.
    df = df[~df["symbol"].str.contains(r"[\$\^=]", regex=True)]
    kw = "|".join(k.lower() for k in ucfg.get("exclude_name_keywords", []))
    if kw:
        df = df[~df["name"].str.lower().str.contains(kw, regex=True, na=False)]
    excluded = {s.upper() for s in ucfg.get("exclude_symbols", [])}
    df = df[~df["symbol"].str.upper().isin(excluded)]

    df["yahoo"] = df["symbol"].map(to_yahoo)
    df = df.drop_duplicates("yahoo")[["symbol", "yahoo", "name", "exchange"]]
    log.info("Universe: %d common-stock listings", len(df))
    return df.reset_index(drop=True)
