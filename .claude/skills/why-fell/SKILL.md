---
name: why-fell
description: Explains why a stock recently dropped. Uses recent price/RSI data plus web search to identify the proximate cause — earnings, guidance, downgrades, news, sector or macro moves from the last 1–5 trading days. Use when the user asks about a sharp drawdown or wants a "why" on a stock that's selling off (e.g. "why did NET fall", "/why-fell CRWV", "what happened with VRT", "explain the drop in AVGO").
---

# Why did this stock fall?

## Input
A US stock ticker symbol that recently dropped. If the user passed a company name, resolve to a ticker first.

## Process

1. Pull recent 4h bars + RSI to confirm and frame the move. Run from the repo root with the project venv:

   ```bash
   .venv/bin/python -c "
   from scripts.fetch_prices import fetch_4h_bars, drop_in_progress_bar
   from scripts.compute_rsi import attach_rsi
   t = 'TICKER_HERE'
   data = fetch_4h_bars([t])
   df = drop_in_progress_bar(data[t])
   df = attach_rsi(df).dropna(subset=['RSI_14']).tail(10)
   print(df[['Open','High','Low','Close','Volume','RSI_14']].round(2).to_string())
   "
   ```

   Note the most recent close, the RSI, and how far the stock has fallen across the last few bars. Look for a volume spike on the down move.

2. Use WebSearch to find news, earnings reports, guidance changes, analyst actions, sector rotations, or macro events from the last 1–5 trading days that explain the drop. Search the ticker and recent date range. Cite sources.

3. Write a 2–3 paragraph note:

   - Lead with the proximate catalyst.
   - State the date and size of the move ("Closed at $X on YYYY-MM-DD, down N% from $Y").
   - Mention named events, executives, products, or analysts where relevant.
   - If no single catalyst, say so and describe the most plausible contributors (sector rotation, macro, technicals).
   - Be honest about uncertainty.

## Rules

- No bullet lists, no section headings — just tight prose, 2–3 paragraphs.
- No filler, no disclaimers, no "investors should..." sentences.
- Cite sources inline with markdown links: [Reuters article](https://...).
- Use the data, not assumptions. If the price data doesn't show a meaningful drop, say so and ask the user what they mean.
