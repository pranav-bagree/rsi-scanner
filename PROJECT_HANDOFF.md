# RSI Oversold Scanner — Project Brief & Handoff

> Paste this as the first message of a fresh Claude Code session in a new project directory. It contains every decision made in the planning phase. Claude Code will have full network access and can actually run yfinance — which the planning session could not.

---

## Goal

Daily-running tool that scans ~100 US stocks across specific sectors, alerts when any stock's 4-hour RSI(14) drops below 25 (oversold), and generates a dashboard with two-part analysis per hit: (1) why the stock fell, (2) thorough fundamental deep-dive.

## High-level architecture

- **Runs on:** GitHub Actions, scheduled cron
- **Schedule:** 9:15 AM ET (pre-market readout — surfaces previous afternoon's close signal before the bell) and 1:35 PM ET (after morning 4h bar closes, 5min buffer for data settling)
- **Primary data source:** yfinance (free, batchable, 730 days of 1h data; single source for v1 — swap later if reliability issues)
- **Analysis model:** Claude Opus 4.7 (`claude-opus-4-7`) — most capable available
- **Output:** HTML dashboard (delivery mechanism TBD — see open items)
- **No persistence in v1** — each run is standalone

## Design decisions (locked)

### RSI calculation
- **14-period Wilder smoothing** (standard, uses EMA with alpha=1/14)
- **Oversold threshold: RSI < 25** (tighter than textbook 30, fewer but stronger signals)
- Computed on 4h bars only; daily/hourly not used for the alert

### 4h bar convention (TradingView style)
yfinance now supports `interval='4h'` natively (validated 2026-05-10). Bars are anchored to market open in ET, identical to TradingView's convention:
- **Bar 1 (morning):** 9:30 ET – 13:30 ET (full 4h)
- **Bar 2 (afternoon):** 13:30 ET – 16:00 ET (partial 2.5h)
- Two bars per regular trading day
- Regular session only — no pre/post-market
- **Signal only on closed bars** — drop the in-progress afternoon bar when scanning mid-session

### Analysis pipeline (per oversold hit)
Two separate Claude Opus 4.7 API calls per oversold ticker. Two-call structure (not combined) for cleaner outputs and so the deep-dive can be reused on any arbitrary ticker outside the scanner.

1. **"Why it fell" analysis**
   - Inputs: recent price action, volume spike, news from drop window
   - Use the API's web search tool (`web_search_20250305`) to find news from last 1–5 trading days
   - Output: 2–3 paragraphs on proximate cause(s)

2. **"Stock deep dive" analysis**
   - Inputs from yfinance: business summary, valuation (P/E trailing & forward, P/S, EV/EBITDA, PEG, P/B), balance sheet (debt/equity, current ratio, cash, FCF), growth (revenue, earnings, margin trend), recent earnings + guidance, analyst ratings + price targets, insider transactions, short interest
   - Output: structured sections — Business, Valuation, Financial Health, Growth & Outlook, Risks, Bull/Bear Case, Bottom Line

## Repo structure to scaffold

```
rsi-scanner/
├── .github/workflows/
│   └── daily-scan.yml           # cron 9:15 ET (14:15 UTC) & 1:35 ET (18:35 UTC)
├── SKILL.md                     # how Claude runs the analysis pass
├── config/
│   ├── universe.yaml            # sector → tickers (USER WILL PROVIDE)
│   └── settings.yaml            # threshold, lookback, periods
├── scripts/
│   ├── fetch_prices.py          # batched yfinance 1h pulls
│   ├── compute_rsi.py           # 4h resample + Wilder RSI
│   ├── why_it_fell.py           # short-term news analysis call
│   ├── deep_dive.py             # fundamentals analysis call
│   └── render_dashboard.py      # HTML output
├── tests/
│   └── test_rsi.py              # hand-computed fixtures, RSI math validation
├── output/
│   └── dashboard-YYYY-MM-DD-HHMM.html
├── requirements.txt
└── README.md
```

## Open items (decisions still needed)

1. ~~**Sector/ticker universe**~~ — **LOCKED 2026-05-10**: 48 tickers across 12 AI-infrastructure subcategories (compute, foundry, custom silicon, optical devices, optical components, networking, servers, power/cooling, data center operators, energy, memory/storage, hyperscalers, EDA). See `config/universe.yaml`.
2. **EDGAR 10-K/10-Q parsing** — defer to v2 or include in v1? Adds depth to deep-dive but increases complexity.
3. **Dashboard delivery** — HTML only (open file locally), GitHub Pages (public web URL), Slack alert when ≥1 hit, or email digest? GitHub Actions chosen as the runner, so any of these work.

---

## ⚠️ FIRST TASK BEFORE BUILDING ANYTHING — *(completed 2026-05-10)*

> **Status:** validated. NET 4h RSI on 2026-05-08 close = **37.99** (RSI=38.88 on the earnings-day morning bar). Numbers cross-checked against TradingView bar-for-bar within tolerance. Native `interval='4h'` matches the 1h-resample exactly.

**Validate the 4h RSI methodology on NET (Cloudflare) against TradingView before scaffolding the rest of the repo.**

NET is a great test case: it dropped ~24% on May 8, 2026 after Q1 2026 earnings (beat on revenue/EPS but announced 1,100 layoffs and weak Q2 guidance). Investing.com showed daily RSI(14) = 27.84 on May 8. The 4h RSI should be in similar territory or lower.

### Validation script

Save this as `net_rsi_demo.py` in a scratch directory and run it:

```python
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

in_progress = agg[~agg["complete"]]
if len(in_progress) > 0:
    ip = in_progress.iloc[-1]
    print(f"\n--- In-progress bar (NOT used for signal) ---")
    print(f"  Bucket start: {in_progress.index[-1]}")
    print(f"  Bars so far:  {int(ip['bars_in_bucket'])}/{int(ip['expected'])}")
    print(f"  Current close: ${ip['Close']:.2f}")
```

### Validation checks

After running it:
1. Open NET on TradingView, switch to 4h timeframe, overlay RSI(14).
2. Confirm two 4h bars per trading day, timestamped 9:30 ET and 13:30 ET.
3. Compare the script's last few RSI values against TradingView's RSI panel at the same bar closes.
4. Acceptable variance: ~0.1–0.5 due to data source differences (yfinance vs TradingView's source) and potential extended-hours handling.

If values match → scaffold the full repo.
If they diverge significantly → debug timezone/bar-edge handling before building further.

---

## What to do first in this Claude Code session

1. Read this brief.
2. Create a scratch dir, drop in `net_rsi_demo.py`, install deps, run it.
3. Report the output back. User will cross-check vs TradingView.
4. Once validated, scaffold the repo structure above. User will provide the sector universe at that point.
