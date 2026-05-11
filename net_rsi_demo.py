"""
4h RSI demo — single ticker, TradingView convention.

Pulls 1h bars from yfinance and resamples to 4h:
  Bar 1 (morning):   09:30-13:30 ET  (full 4h, aggregates 4 hourly bars)
  Bar 2 (afternoon): 13:30-16:00 ET  (partial 2.5h, aggregates 3 hourly bars; last is 30min)

Then computes 14-period Wilder RSI on the 4h close series.

Usage:
    pip install yfinance pandas
    python net_rsi_demo.py NET
"""

import sys
import yfinance as yf
import pandas as pd

TICKER = sys.argv[1] if len(sys.argv) > 1 else "NET"


def session_bucket(ts: pd.Timestamp):
    """Map a 1h bar's start timestamp to its 4h bucket (TradingView convention)."""
    t = ts.time()
    date = ts.date()
    morning_start = pd.Timestamp("09:30").time()
    afternoon_start = pd.Timestamp("13:30").time()
    close = pd.Timestamp("16:00").time()
    if morning_start <= t < afternoon_start:
        return pd.Timestamp(f"{date} 09:30", tz="America/New_York")
    if afternoon_start <= t < close:
        return pd.Timestamp(f"{date} 13:30", tz="America/New_York")
    return pd.NaT  # outside regular session


def wilder_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """14-period Wilder RSI. Uses ewm with alpha=1/period (Wilder's smoothing)."""
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# --- 1. Pull 60 days of 1h bars ---
df = yf.download(TICKER, period="60d", interval="1h", auto_adjust=False, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
else:
    df.index = df.index.tz_convert("America/New_York")

print(f"Pulled {len(df)} 1h bars for {TICKER}")
print(f"  First: {df.index[0]}")
print(f"  Last:  {df.index[-1]}\n")

# --- 2. Resample to 4h ---
df["bucket"] = df.index.map(session_bucket)
df = df.dropna(subset=["bucket"])

agg = df.groupby("bucket").agg(
    Open=("Open", "first"),
    High=("High", "max"),
    Low=("Low", "min"),
    Close=("Close", "last"),
    Volume=("Volume", "sum"),
    bars_in_bucket=("Close", "count"),
).sort_index()

agg["expected"] = [4 if t.time() == pd.Timestamp("09:30").time() else 3 for t in agg.index]
agg["complete"] = agg["bars_in_bucket"] >= agg["expected"]

# --- 3. RSI on closed bars only ---
closed = agg[agg["complete"]].copy()
closed["RSI_14"] = wilder_rsi(closed["Close"], period=14)

# --- 4. Print results ---
print(f"=== Last 15 closed 4h bars for {TICKER} ===")
out = closed.tail(15)[["Open", "High", "Low", "Close", "Volume", "RSI_14"]].round(2)
print(out.to_string())

print(f"\n--- Most recent closed 4h bar ---")
last = closed.iloc[-1]
print(f"  Bucket start: {closed.index[-1]}")
print(f"  Session:      {'Morning (9:30-13:30)' if closed.index[-1].time() == pd.Timestamp('09:30').time() else 'Afternoon (13:30-16:00)'}")
print(f"  Close:        ${last['Close']:.2f}")
print(f"  RSI(14):      {last['RSI_14']:.2f}")
print(f"  Oversold (<25)? {'YES — would alert' if last['RSI_14'] < 25 else 'no'}")

# Also show the in-progress bar if there is one (for context, not for signaling)
in_progress = agg[~agg["complete"]]
if len(in_progress) > 0:
    ip = in_progress.iloc[-1]
    print(f"\n--- In-progress bar (NOT used for signal) ---")
    print(f"  Bucket start: {in_progress.index[-1]}")
    print(f"  Bars so far:  {int(ip['bars_in_bucket'])}/{int(ip['expected'])}")
    print(f"  Current close: ${ip['Close']:.2f}")
