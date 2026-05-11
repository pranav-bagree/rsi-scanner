"""Claude Opus 4.7 fundamental deep-dive using yfinance .info / financial properties."""

from __future__ import annotations

import json
import yfinance as yf
from anthropic import Anthropic


SYSTEM_PROMPT = """You are a buy-side equity analyst writing a thorough single-name research note.

Output structure (use these exact section headings, in this order, as plain markdown):

## Business
What the company does, key segments, customers, and competitive position. 1 paragraph.

## Valuation
Walk through the multiples (P/E, forward P/E, P/S, EV/EBITDA, PEG, P/B). Compare to history and to peers where you can reason about it. State whether the stock looks cheap, fair, or expensive on these numbers. 1-2 paragraphs.

## Financial Health
Balance sheet, leverage, liquidity, free cash flow. Is this a fortress balance sheet or stressed? 1 paragraph.

## Growth & Outlook
Recent revenue/earnings growth, margin trajectory, guidance, secular drivers. 1-2 paragraphs.

## Risks
The 3-4 most material risks specific to this company, ranked. Bullet list ok here.

## Bull / Bear Case
Two short paragraphs side by side conceptually — one paragraph for bull, one for bear.

## Bottom Line
2-3 sentences. Clear stance: would you initiate a position here, wait, or pass? Why?

Rules:
- Use ONLY the data provided. If a field is missing or null, say so explicitly rather than guessing.
- No filler, no boilerplate disclaimers, no "investors should..." sentences.
- Specific numbers beat vague adjectives. Always cite the metric you used.
- Tone: direct, opinionated, professional.
"""


def _safe(d: dict, key: str, default=None):
    v = d.get(key, default)
    if v is None:
        return default
    return v


def gather_fundamentals(ticker: str) -> dict:
    """Pull a structured fundamentals snapshot from yfinance."""
    yt = yf.Ticker(ticker)
    info = yt.info or {}

    snapshot = {
        "ticker": ticker,
        "company": _safe(info, "longName") or _safe(info, "shortName"),
        "sector": _safe(info, "sector"),
        "industry": _safe(info, "industry"),
        "business_summary": _safe(info, "longBusinessSummary"),
        "current_price": _safe(info, "currentPrice"),
        "market_cap": _safe(info, "marketCap"),
        "enterprise_value": _safe(info, "enterpriseValue"),
        "valuation": {
            "trailing_pe": _safe(info, "trailingPE"),
            "forward_pe": _safe(info, "forwardPE"),
            "price_to_sales": _safe(info, "priceToSalesTrailing12Months"),
            "ev_to_ebitda": _safe(info, "enterpriseToEbitda"),
            "ev_to_revenue": _safe(info, "enterpriseToRevenue"),
            "peg_ratio": _safe(info, "pegRatio") or _safe(info, "trailingPegRatio"),
            "price_to_book": _safe(info, "priceToBook"),
        },
        "financial_health": {
            "debt_to_equity": _safe(info, "debtToEquity"),
            "current_ratio": _safe(info, "currentRatio"),
            "quick_ratio": _safe(info, "quickRatio"),
            "total_cash": _safe(info, "totalCash"),
            "total_debt": _safe(info, "totalDebt"),
            "free_cashflow": _safe(info, "freeCashflow"),
            "operating_cashflow": _safe(info, "operatingCashflow"),
            "return_on_equity": _safe(info, "returnOnEquity"),
            "return_on_assets": _safe(info, "returnOnAssets"),
        },
        "growth_and_margins": {
            "revenue_growth_yoy": _safe(info, "revenueGrowth"),
            "earnings_growth_yoy": _safe(info, "earningsGrowth"),
            "earnings_quarterly_growth_yoy": _safe(info, "earningsQuarterlyGrowth"),
            "gross_margin": _safe(info, "grossMargins"),
            "operating_margin": _safe(info, "operatingMargins"),
            "profit_margin": _safe(info, "profitMargins"),
            "ebitda_margin": _safe(info, "ebitdaMargins"),
            "total_revenue_ttm": _safe(info, "totalRevenue"),
        },
        "analyst_view": {
            "recommendation_key": _safe(info, "recommendationKey"),
            "recommendation_mean": _safe(info, "recommendationMean"),
            "number_of_analysts": _safe(info, "numberOfAnalystOpinions"),
            "target_mean_price": _safe(info, "targetMeanPrice"),
            "target_high_price": _safe(info, "targetHighPrice"),
            "target_low_price": _safe(info, "targetLowPrice"),
        },
        "ownership_and_short": {
            "held_by_insiders_pct": _safe(info, "heldPercentInsiders"),
            "held_by_institutions_pct": _safe(info, "heldPercentInstitutions"),
            "short_ratio": _safe(info, "shortRatio"),
            "short_percent_of_float": _safe(info, "shortPercentOfFloat"),
            "shares_short": _safe(info, "sharesShort"),
        },
        "dividend": {
            "dividend_yield": _safe(info, "dividendYield"),
            "payout_ratio": _safe(info, "payoutRatio"),
        },
    }

    try:
        earnings_dates = yt.earnings_dates
        if earnings_dates is not None and not earnings_dates.empty:
            past = earnings_dates.dropna(subset=["Reported EPS"]).head(4)
            snapshot["recent_earnings"] = [
                {
                    "date": str(idx.date()),
                    "eps_estimate": float(row["EPS Estimate"]) if row.get("EPS Estimate") and row["EPS Estimate"] == row["EPS Estimate"] else None,
                    "reported_eps": float(row["Reported EPS"]) if row.get("Reported EPS") and row["Reported EPS"] == row["Reported EPS"] else None,
                    "surprise_pct": float(row["Surprise(%)"]) if row.get("Surprise(%)") and row["Surprise(%)"] == row["Surprise(%)"] else None,
                }
                for idx, row in past.iterrows()
            ]
    except Exception:
        pass

    return snapshot


def analyze_deep_dive(
    ticker: str,
    company_name: str,
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 4096,
) -> dict:
    fundamentals = gather_fundamentals(ticker)
    client = Anthropic()

    user_msg = f"""Write the research note for {ticker} ({company_name}).

Fundamentals snapshot from yfinance (treat as authoritative for numbers):

```json
{json.dumps(fundamentals, indent=2, default=str)}
```
"""

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    text = "".join(b.text for b in message.content if b.type == "text").strip()

    return {
        "text": text,
        "fundamentals": fundamentals,
        "stop_reason": message.stop_reason,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }
