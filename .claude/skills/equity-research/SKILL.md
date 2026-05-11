---
name: equity-research
description: Produces a full sell-side-style equity research report on a single US stock — executive summary with rating and target range, multi-year financials review, peer comparison, capital allocation analysis, technical context, insider/institutional activity, three-scenario valuation (bull/base/bear), catalyst calendar, and a clear recommendation. Use when the user wants a thorough professional research note rather than a quick read (e.g. "full research on NVDA", "/equity-research VRT", "give me the deep equity research on MU", "professional report on CRWV").
---

# Professional equity research report

## Input
A US stock ticker symbol (e.g. NVDA, VRT, CRWV). If the user passed a company name, resolve to a ticker; if ambiguous, ask once.

## Process

### 1. Gather the data
Run from the repo root with the project venv. This pulls a comprehensive snapshot (~85KB JSON) covering identity, multiples, multi-year statements, quarterly statements, price stats, 4h RSI, earnings history, upcoming calendar, analyst actions, insider activity, holders, recent news, and same-subcategory peers from `config/universe.yaml`:

```bash
.venv/bin/python -m scripts.equity_research TICKER_HERE --pretty
```

Read the JSON carefully. Every numbered metric you cite in the report must come from this data (or from a sourced web search you do explicitly in step 2).

### 2. Optional supplemental research
If the snapshot is missing context — recent earnings commentary, regulatory filings, strategic announcements, sector dynamics — use WebSearch to fill gaps. Always cite sources inline with markdown links: `[Source](https://...)`. Don't search just to pad — only when the JSON leaves a real gap for your stance.

### 3. Write the report
Use exactly the section headings below, in this order. Save the rendered report to `output/research/{TICKER}-{YYYY-MM-DD}.md` (create the directory if needed) AND display it in the chat.

```markdown
# {TICKER} — {Company Name}
**As of:** {date}  ·  **Price:** ${current}  ·  **Market cap:** ${formatted}  ·  **Rating:** {Buy / Hold / Sell}  ·  **12-month target range:** ${low}–${high}

## Executive Summary
Three to five sentences. Lead with the thesis, then the rating, then the catalyst that resolves the trade. Be specific.

## Business Overview
What the company does, key segments and revenue mix, customer concentration, geographic exposure. One to two paragraphs.

## Industry & Competitive Position
Industry structure, growth dynamics, the company's moats (cost, switching, network, IP, regulatory, scale), and who its main competitors are. Reference the same-subcategory peers from the snapshot where it adds signal.

## Financial Performance
Walk through multi-year revenue, gross margin, operating margin, net income, and FCF using the annual statements. Then the most recent quarter or two from the quarterly statements. Capital efficiency: ROE, ROA, and any directional ROIC commentary you can support. State trajectory plainly — accelerating, decelerating, inflecting.

## Valuation
Build a peer comparables table from the `same_subcategory_peers` section. Format:

| Ticker | Market Cap | Fwd P/E | P/S | EV/EBITDA | Rev Growth | Op Margin |
|--------|-----------|---------|-----|-----------|------------|-----------|

Then walk through the subject's multiples vs the peer median and vs its own history (using historical data you can derive from the statements where possible). Conclude with a cheap / fair / expensive verdict and the implied price target range based on a fair multiple × forward earnings or FCF.

## Capital Allocation
Buybacks, dividends, M&A pattern, capex intensity, R&D as % of revenue. Use the cashflow statements. Is management compounding shareholder value or destroying it?

## Catalysts & Calendar
Near-term (next 30–90 days) from `upcoming_calendar` and `earnings_history` — next earnings date, expected EPS, recent surprise pattern. Mid-term (3–12 months) — product cycles, secular tailwinds. Use news headlines from the snapshot.

## Bull / Base / Bear Scenarios
For each: a one-sentence setup, the key assumption that differs from base, and a 12-month price target. Format:

> **Bull (X% probability):** {one-sentence thesis}. Implied target: ${X} ({+Y}%).
> **Base (X% probability):** ...
> **Bear (X% probability):** ...

Probabilities should sum to 100. Be honest — don't anchor on bullish.

## Technical Context
Use `price_stats_1y` and `technical_4h_rsi`. Current price vs 50d and 200d MA, distance from 52w high/low, where the 4h RSI sits, any oversold/overbought condition. Note key levels if obvious from the data.

## Insider & Institutional Activity
Recent insider purchases vs sales (net dollars, direction). Top institutional holders and any notable position changes if visible. Short interest level and direction. State clearly whether smart money is leaning in or out.

## Risks
Three to five most material risks, ranked, each with one or two sentences explaining how it would damage the thesis. Bullet list.

## Bottom Line
Two or three sentences. Reaffirm the rating, name the single catalyst you'd watch most closely, and state position-sizing guidance (e.g. "starter position around 1-2%", "wait for a pullback below $X", "full-size on confirmed breakout above $Y").
```

## Rules

- **Data integrity is non-negotiable.** Every quantitative claim must come from the JSON snapshot or an explicitly-cited web source. If a field is null or missing, write "not available" — never fabricate a number, growth rate, or analyst consensus.
- **Numbers beat adjectives.** "Revenue grew 31% YoY" beats "strong growth." "FCF margin expanded from 12% to 24%" beats "improving cash generation."
- **Take a stance.** This is a research report, not a Wikipedia entry. The rating must be unambiguous. The thesis must be specific.
- **No filler.** No "investors should consult their financial advisor," no "this report is for informational purposes," no boilerplate.
- **Concise where possible.** Aim for ~1500-2500 words total — comprehensive but not bloated.
- **Cite web sources** with inline markdown links wherever you used them.
- **Save the file.** Always write to `output/research/{TICKER}-{YYYY-MM-DD}.md` so the user has a permanent record.
