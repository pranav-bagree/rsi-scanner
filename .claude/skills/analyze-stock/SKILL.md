---
name: analyze-stock
description: Produces a thorough buy-side fundamental research note on a single US stock — business overview, valuation, financial health, growth outlook, risks, bull/bear case, and a clear bottom-line stance. Use when the user wants to evaluate, research, or get a deep-dive on a specific ticker (e.g. "analyze NVDA", "/analyze-stock CRWV", "what's the case for VST?", "deep dive on MU").
---

# Stock fundamental deep-dive

## Input
A US stock ticker symbol (passed by the user, e.g. NVDA, CRWV, VST). If the user gave a company name, resolve it to a ticker first; ask if ambiguous.

## Process

1. Pull a fundamentals snapshot from yfinance using the project's existing helper. Run from the repo root with the project venv:

   ```bash
   .venv/bin/python -c "
   from scripts.deep_dive import gather_fundamentals
   import json
   print(json.dumps(gather_fundamentals('TICKER_HERE'), default=str, indent=2))
   "
   ```

   Replace `TICKER_HERE` with the ticker. The output is JSON with `business_summary`, `valuation`, `financial_health`, `growth_and_margins`, `analyst_view`, `ownership_and_short`, `dividend`, and `recent_earnings` sections.

2. If the business summary is missing/thin or the company is unfamiliar, optionally use WebSearch to fill the gap.

3. Write the research note. Use these exact section headings, in this order:

   ## Business
   What the company does, key segments, customers, competitive position. One paragraph.

   ## Valuation
   Walk through the multiples (P/E, forward P/E, P/S, EV/EBITDA, PEG, P/B). State whether the stock looks cheap, fair, or expensive on these numbers; compare to sector/history where you can reason about it. 1–2 paragraphs.

   ## Financial Health
   Balance sheet, leverage, liquidity, free cash flow. Fortress balance sheet or stressed? One paragraph.

   ## Growth & Outlook
   Recent revenue/earnings growth, margin trajectory, guidance, secular drivers. 1–2 paragraphs.

   ## Risks
   The 3–4 most material risks specific to this company, ranked. Bullet list ok.

   ## Bull / Bear Case
   Two short paragraphs — one for bull, one for bear.

   ## Bottom Line
   2–3 sentences. Clear stance: initiate a position here, wait, or pass? Why?

## Rules

- Use ONLY the data from the yfinance snapshot and (if used) web search. If a field is missing or null, say so explicitly rather than guessing.
- No filler, no boilerplate disclaimers, no "investors should consult..." sentences.
- Specific numbers beat vague adjectives. Always cite the metric you used.
- Tone: direct, opinionated, professional.
