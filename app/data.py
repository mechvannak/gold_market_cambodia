"""Market data via Yahoo Finance (free, no key)."""
import pandas as pd
import yfinance as yf

GOLD = "GC=F"  # COMEX gold futures, USD per troy ounce
MACRO = {
    "dxy": "DX-Y.NYB",  # US dollar index
    "us10y": "^TNX",  # US 10-year Treasury yield
    "vix": "^VIX",  # equity volatility (risk-off gauge)
}


def fetch_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def fetch_market() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    gold = fetch_history(GOLD)
    if gold.empty:
        raise RuntimeError("Could not download gold prices from Yahoo Finance")
    macro: dict[str, pd.DataFrame] = {}
    for key, symbol in MACRO.items():
        try:
            df = fetch_history(symbol, "3mo")
            if not df.empty:
                macro[key] = df
        except Exception:  # a missing macro series should not break the forecast
            continue
    return gold, macro
