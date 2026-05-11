"""Claude Opus 4.7 'why it fell' analysis — uses web search to find news from the drop window."""

from __future__ import annotations

import os
from anthropic import Anthropic


SYSTEM_PROMPT = """You are a sell-side equity analyst writing a short, focused note explaining what caused a recent sharp drawdown in a stock.

Your output must be:
- 2-3 tight paragraphs (no bullet lists, no headings).
- Cause-first: lead with the proximate catalyst (earnings, guidance, macro, sector rotation, ratings change, news, etc.).
- Specific. Cite the date and the move. Mention named events, executives, products, or analysts where relevant.
- Sourced. Use the provided web_search tool to find news from the last 1-5 trading days before writing. Do not invent facts.
- Honest about uncertainty. If the move has no obvious single catalyst, say so and describe the most plausible contributors.
- No disclaimers, no "investors should consult..." filler, no preamble.
"""


def analyze_why_it_fell(
    ticker: str,
    company_name: str,
    recent_bars: list[dict],
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 4096,
    web_search_max_uses: int = 5,
) -> dict:
    """Returns {'text': str, 'citations': list[{title, url}], 'stop_reason': str}."""
    client = Anthropic()

    last = recent_bars[-1]
    first = recent_bars[0]
    move_pct = (last["close"] - first["close"]) / first["close"] * 100
    bars_table = "\n".join(
        f"  {b['ts']}  O={b['open']:.2f}  H={b['high']:.2f}  L={b['low']:.2f}  C={b['close']:.2f}  V={b['volume']:,.0f}  RSI={b['rsi']:.2f}"
        for b in recent_bars
    )

    user_msg = f"""Ticker: {ticker} ({company_name})

This stock just triggered an oversold signal: 4h RSI(14) closed at {last['rsi']:.2f} (threshold = 25).

Recent 4h bars (most recent last):
{bars_table}

Window summary: {first['ts']} close ${first['close']:.2f} to {last['ts']} close ${last['close']:.2f} = {move_pct:+.1f}%.

Search for news, earnings, guidance, downgrades, sector moves, or macro events from the last 5 trading days that explain this drop. Write the analysis."""

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": web_search_max_uses,
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    text_parts = []
    citations: list[dict] = []
    for block in message.content:
        if block.type == "text":
            text_parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                cit_dict = {
                    "title": getattr(cit, "title", "") or "",
                    "url": getattr(cit, "url", "") or "",
                }
                if cit_dict["url"] and cit_dict not in citations:
                    citations.append(cit_dict)

    return {
        "text": "\n\n".join(p.strip() for p in text_parts if p.strip()),
        "citations": citations,
        "stop_reason": message.stop_reason,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }
