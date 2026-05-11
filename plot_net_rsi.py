"""Plot 4h price + RSI(14) for a ticker. Reuses logic from net_rsi_demo.py."""

import sys
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

TICKER = sys.argv[1] if len(sys.argv) > 1 else "NET"


def session_bucket(ts: pd.Timestamp):
    t = ts.time()
    date = ts.date()
    morning_start = pd.Timestamp("09:30").time()
    afternoon_start = pd.Timestamp("13:30").time()
    close = pd.Timestamp("16:00").time()
    if morning_start <= t < afternoon_start:
        return pd.Timestamp(f"{date} 09:30", tz="America/New_York")
    if afternoon_start <= t < close:
        return pd.Timestamp(f"{date} 13:30", tz="America/New_York")
    return pd.NaT


def wilder_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


df = yf.download(TICKER, period="60d", interval="1h", auto_adjust=False, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
else:
    df.index = df.index.tz_convert("America/New_York")

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

closed = agg[agg["complete"]].copy()
closed["RSI_14"] = wilder_rsi(closed["Close"], period=14)
closed = closed.dropna(subset=["RSI_14"])

# Plot last ~30 trading days of closed bars
plot_df = closed.tail(60)

fig, (ax_price, ax_rsi) = plt.subplots(
    2, 1, figsize=(14, 8), sharex=True,
    gridspec_kw={"height_ratios": [2, 1]},
)

# Price panel — candlestick-ish using high/low wicks + open/close body
for ts, row in plot_df.iterrows():
    color = "#26a69a" if row["Close"] >= row["Open"] else "#ef5350"
    ax_price.plot([ts, ts], [row["Low"], row["High"]], color=color, linewidth=0.8)
    ax_price.plot([ts, ts], [row["Open"], row["Close"]], color=color, linewidth=4)

ax_price.set_title(f"{TICKER} — 4h bars (TradingView convention) — last {len(plot_df)} closed bars")
ax_price.set_ylabel("Price ($)")
ax_price.grid(True, alpha=0.3)

# RSI panel
ax_rsi.plot(plot_df.index, plot_df["RSI_14"], color="#7e57c2", linewidth=1.5, label="RSI(14)")
ax_rsi.axhline(70, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
ax_rsi.axhline(30, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
ax_rsi.axhline(25, color="red", linestyle="-", linewidth=1.2, alpha=0.8, label="Oversold threshold (25)")
ax_rsi.fill_between(plot_df.index, 0, 25, color="red", alpha=0.08)
ax_rsi.set_ylim(0, 100)
ax_rsi.set_ylabel("RSI(14)")
ax_rsi.set_xlabel("Bar bucket start (ET)")
ax_rsi.grid(True, alpha=0.3)
ax_rsi.legend(loc="upper left", fontsize=9)

# Annotate most recent bar
last_ts = plot_df.index[-1]
last_rsi = plot_df["RSI_14"].iloc[-1]
last_close = plot_df["Close"].iloc[-1]
ax_rsi.annotate(
    f"  {last_ts.strftime('%m-%d %H:%M')}\n  RSI={last_rsi:.2f}",
    xy=(last_ts, last_rsi), xytext=(10, 10), textcoords="offset points",
    fontsize=9, color="#7e57c2",
)
ax_price.annotate(
    f"  ${last_close:.2f}",
    xy=(last_ts, last_close), xytext=(10, 0), textcoords="offset points",
    fontsize=9,
)

ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
ax_rsi.xaxis.set_major_locator(mdates.DayLocator(interval=3))
plt.setp(ax_rsi.get_xticklabels(), rotation=30, ha="right")

plt.tight_layout()
out_path = f"{TICKER}_4h_rsi.png"
plt.savefig(out_path, dpi=140, bbox_inches="tight")
print(f"Saved {out_path}")
