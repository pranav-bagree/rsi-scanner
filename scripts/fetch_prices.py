"""Batched 4h OHLCV fetch from yfinance, all tickers in one call."""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_4h_bars(tickers: list[str], period: str = "3mo") -> dict[str, pd.DataFrame]:
    """Pull 4h bars for every ticker in one batched call. Returns {ticker: ohlcv_df}.

    yfinance's native interval='4h' produces 9:30 ET and 13:30 ET bucket starts —
    identical to TradingView's convention. Timestamps converted to America/New_York.
    """
    raw = yf.download(
        tickers=" ".join(tickers),
        period=period,
        interval="4h",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    out: dict[str, pd.DataFrame] = {}
    is_multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = raw[t].copy() if is_multi else raw.copy()
        except KeyError:
            continue
        df = df.dropna(how="all")
        if df.empty:
            continue
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("America/New_York")
        out[t] = df[["Open", "High", "Low", "Close", "Volume"]]
    return out


def drop_in_progress_bar(df: pd.DataFrame, now_et: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the last bar if its bucket hasn't closed yet (mid-session run)."""
    if df.empty:
        return df
    if now_et is None:
        now_et = pd.Timestamp.now(tz="America/New_York")
    last_ts = df.index[-1]
    if last_ts.time() == pd.Timestamp("09:30").time():
        bar_close = last_ts.replace(hour=13, minute=30)
    elif last_ts.time() == pd.Timestamp("13:30").time():
        bar_close = last_ts.replace(hour=16, minute=0)
    else:
        return df
    return df.iloc[:-1] if now_et < bar_close else df
