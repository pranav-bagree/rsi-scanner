"""4h RSI demo using yfinance's native interval='4h' (no resample needed)."""

import sys
import yfinance as yf
import pandas as pd

TICKER = sys.argv[1] if len(sys.argv) > 1 else "NET"


def wilder_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


df = yf.download(TICKER, period="3mo", interval="4h", auto_adjust=False, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
df.index = df.index.tz_convert("America/New_York")

# Drop in-progress afternoon bar if we're mid-session. Yahoo's afternoon bar
# spans 13:30-16:00 ET (2.5h); only treat it as closed once the session has ended.
now_et = pd.Timestamp.now(tz="America/New_York")
last_ts = df.index[-1]
if last_ts.time() == pd.Timestamp("13:30").time():
    bar_close = last_ts.replace(hour=16, minute=0)
    if now_et < bar_close:
        df = df.iloc[:-1]
elif last_ts.time() == pd.Timestamp("09:30").time():
    bar_close = last_ts.replace(hour=13, minute=30)
    if now_et < bar_close:
        df = df.iloc[:-1]

df["RSI_14"] = wilder_rsi(df["Close"], period=14)

print(f"Pulled {len(df)} closed 4h bars for {TICKER}")
print(f"  First: {df.index[0]}")
print(f"  Last:  {df.index[-1]}\n")

print(f"=== Last 15 closed 4h bars for {TICKER} ===")
print(df.tail(15)[["Open", "High", "Low", "Close", "Volume", "RSI_14"]].round(2).to_string())

last = df.iloc[-1]
print(f"\n--- Most recent closed 4h bar ---")
print(f"  Bucket start: {df.index[-1]}")
print(f"  Session:      {'Morning (9:30-13:30)' if df.index[-1].time() == pd.Timestamp('09:30').time() else 'Afternoon (13:30-16:00)'}")
print(f"  Close:        ${last['Close']:.2f}")
print(f"  RSI(14):      {last['RSI_14']:.2f}")
print(f"  Oversold (<25)? {'YES — would alert' if last['RSI_14'] < 25 else 'no'}")
