"""Comprehensive single-ticker data pull for the /equity-research skill.

Produces a thorough JSON snapshot covering:
  - Identity, business summary, classification
  - Wide-format current-state metrics (valuation, financial health, growth, margins)
  - Multi-year annual income / balance / cash flow statements
  - Quarterly statements (most recent 4-6 quarters)
  - Recent earnings + upcoming calendar
  - Analyst recommendations and recent upgrades/downgrades
  - Holders, insider transactions, short interest
  - News headlines
  - Price stats over 1y (52w high/low, distance to moving averages, drawdown from 52w high)
  - Same-subcategory peers from config/universe.yaml when available
  - 4h RSI from this scanner's own pipeline for technical context

Every section is wrapped in try/except so partial yfinance failures don't kill the whole snapshot.

Usage:
    .venv/bin/python -m scripts.equity_research NVDA            # JSON to stdout
    .venv/bin/python -m scripts.equity_research NVDA --pretty   # human-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent


def _safe(d: dict, key: str, default=None):
    v = d.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and v != v:  # NaN
        return default
    return v


def _df_to_records(df: pd.DataFrame | None, *, max_cols: int | None = None) -> list[dict] | None:
    """Convert a yfinance financial DataFrame (rows=line items, cols=periods) to a list of period records."""
    if df is None or df.empty:
        return None
    df = df.copy()
    if max_cols is not None:
        df = df.iloc[:, :max_cols]
    records = []
    for col in df.columns:
        period = str(col.date()) if hasattr(col, "date") else str(col)
        rec = {"period": period}
        for idx, val in df[col].items():
            if pd.isna(val):
                continue
            try:
                rec[str(idx)] = float(val)
            except (TypeError, ValueError):
                rec[str(idx)] = str(val)
        records.append(rec)
    return records


def _peers_from_universe(ticker: str) -> list[str] | None:
    """If the ticker is in our universe, return its same-subcategory peers."""
    universe_path = ROOT / "config" / "universe.yaml"
    if not universe_path.exists():
        return None
    try:
        with universe_path.open() as f:
            data = yaml.safe_load(f)
        for sector, items in data.get("sectors", {}).items():
            tickers = [it["ticker"] for it in items]
            if ticker in tickers:
                return [{"ticker": t, "subcategory": sector} for t in tickers if t != ticker]
    except Exception:
        pass
    return None


def _peer_snapshot(peers: list[dict] | None) -> list[dict] | None:
    """Pull a tiny multiple-snapshot for each peer ticker."""
    if not peers:
        return None
    out = []
    for p in peers:
        t = p["ticker"]
        try:
            info = yf.Ticker(t).info or {}
            out.append(
                {
                    "ticker": t,
                    "subcategory": p["subcategory"],
                    "company": _safe(info, "longName") or _safe(info, "shortName"),
                    "market_cap": _safe(info, "marketCap"),
                    "trailing_pe": _safe(info, "trailingPE"),
                    "forward_pe": _safe(info, "forwardPE"),
                    "price_to_sales": _safe(info, "priceToSalesTrailing12Months"),
                    "ev_to_ebitda": _safe(info, "enterpriseToEbitda"),
                    "peg_ratio": _safe(info, "pegRatio") or _safe(info, "trailingPegRatio"),
                    "revenue_growth_yoy": _safe(info, "revenueGrowth"),
                    "profit_margin": _safe(info, "profitMargins"),
                    "operating_margin": _safe(info, "operatingMargins"),
                }
            )
        except Exception:
            out.append({"ticker": t, "error": True})
    return out


def _price_stats(yt: yf.Ticker) -> dict | None:
    try:
        hist = yt.history(period="1y", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        close = hist["Close"]
        current = float(close.iloc[-1])
        high_52w = float(close.max())
        low_52w = float(close.min())
        ma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
        ma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
        return {
            "current_price": round(current, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "pct_off_52w_high": round((current / high_52w - 1) * 100, 2),
            "pct_above_52w_low": round((current / low_52w - 1) * 100, 2),
            "ma_50d": round(ma50, 2) if ma50 else None,
            "ma_200d": round(ma200, 2) if ma200 else None,
            "pct_vs_ma50": round((current / ma50 - 1) * 100, 2) if ma50 else None,
            "pct_vs_ma200": round((current / ma200 - 1) * 100, 2) if ma200 else None,
            "ytd_return_pct": round((current / float(close.iloc[0]) - 1) * 100, 2),
        }
    except Exception:
        return None


def _rsi_4h(ticker: str) -> dict | None:
    """Pull the scanner's own 4h RSI for technical context."""
    try:
        from scripts.fetch_prices import fetch_4h_bars, drop_in_progress_bar
        from scripts.compute_rsi import attach_rsi

        data = fetch_4h_bars([ticker])
        df = data.get(ticker)
        if df is None or df.empty:
            return None
        df = drop_in_progress_bar(df)
        df = attach_rsi(df).dropna(subset=["RSI_14"])
        if df.empty:
            return None
        recent = df.tail(8)
        return {
            "current_rsi": round(float(df["RSI_14"].iloc[-1]), 2),
            "current_bar_close": round(float(df["Close"].iloc[-1]), 2),
            "current_bar_ts_et": str(df.index[-1]),
            "recent_8_bars": [
                {
                    "ts": str(ts),
                    "close": round(float(r["Close"]), 2),
                    "rsi": round(float(r["RSI_14"]), 2),
                }
                for ts, r in recent.iterrows()
            ],
        }
    except Exception:
        return None


def _news(yt: yf.Ticker, *, limit: int = 8) -> list[dict] | None:
    try:
        items = (yt.news or [])[:limit]
        out = []
        for n in items:
            content = n.get("content") if isinstance(n, dict) else None
            if content:
                out.append(
                    {
                        "title": content.get("title"),
                        "publisher": (content.get("provider") or {}).get("displayName"),
                        "url": (content.get("canonicalUrl") or {}).get("url"),
                        "published": content.get("pubDate"),
                    }
                )
            elif isinstance(n, dict):
                out.append(
                    {
                        "title": n.get("title"),
                        "publisher": n.get("publisher"),
                        "url": n.get("link"),
                        "published": n.get("providerPublishTime"),
                    }
                )
        return [x for x in out if x.get("title")]
    except Exception:
        return None


def _calendar(yt: yf.Ticker) -> dict | None:
    try:
        cal = yt.calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            return {k: (str(v) if v is not None else None) for k, v in cal.items()}
        if hasattr(cal, "to_dict"):
            return {str(k): (str(v) if v is not None else None) for k, v in cal.to_dict().items()}
        return None
    except Exception:
        return None


def _recommendations(yt: yf.Ticker) -> dict | None:
    try:
        rec_summary = yt.recommendations_summary
        upgrades = yt.upgrades_downgrades
        out = {}
        if rec_summary is not None and not rec_summary.empty:
            out["aggregate_recent_periods"] = rec_summary.head(4).to_dict(orient="records")
        if upgrades is not None and not upgrades.empty:
            recent = upgrades.head(15).copy()
            recent.index = recent.index.map(str)
            out["recent_actions"] = [
                {"date": idx, **{k: (str(v) if pd.notna(v) else None) for k, v in row.items()}}
                for idx, row in recent.iterrows()
            ]
        return out or None
    except Exception:
        return None


def _insiders(yt: yf.Ticker) -> dict | None:
    try:
        out = {}
        purchases = yt.insider_purchases
        if purchases is not None and not purchases.empty:
            out["purchase_activity"] = purchases.to_dict(orient="records")
        transactions = yt.insider_transactions
        if transactions is not None and not transactions.empty:
            tx = transactions.head(15).copy()
            for col in tx.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
                tx[col] = tx[col].astype(str)
            out["recent_transactions"] = tx.to_dict(orient="records")
        return out or None
    except Exception:
        return None


def _holders(yt: yf.Ticker) -> dict | None:
    try:
        out = {}
        major = yt.major_holders
        if major is not None and not major.empty:
            out["major_breakdown"] = major.to_dict()
        inst = yt.institutional_holders
        if inst is not None and not inst.empty:
            top = inst.head(10).copy()
            for col in top.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
                top[col] = top[col].astype(str)
            out["top_institutional"] = top.to_dict(orient="records")
        return out or None
    except Exception:
        return None


def _earnings_history(yt: yf.Ticker) -> list[dict] | None:
    try:
        ed = yt.earnings_dates
        if ed is None or ed.empty:
            return None
        recent = ed.dropna(subset=["Reported EPS"]).head(8)
        out = []
        for idx, row in recent.iterrows():
            out.append(
                {
                    "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "eps_estimate": float(row["EPS Estimate"]) if pd.notna(row.get("EPS Estimate")) else None,
                    "reported_eps": float(row["Reported EPS"]) if pd.notna(row.get("Reported EPS")) else None,
                    "surprise_pct": float(row["Surprise(%)"]) if pd.notna(row.get("Surprise(%)")) else None,
                }
            )
        return out
    except Exception:
        return None


def gather_comprehensive(ticker: str) -> dict:
    """Pull the full equity-research snapshot."""
    yt = yf.Ticker(ticker)
    info = {}
    try:
        info = yt.info or {}
    except Exception:
        pass

    snapshot: dict[str, Any] = {
        "ticker": ticker,
        "as_of": str(pd.Timestamp.now(tz="America/New_York")),
        "identity": {
            "company": _safe(info, "longName") or _safe(info, "shortName"),
            "exchange": _safe(info, "exchange"),
            "sector": _safe(info, "sector"),
            "industry": _safe(info, "industry"),
            "country": _safe(info, "country"),
            "website": _safe(info, "website"),
            "full_time_employees": _safe(info, "fullTimeEmployees"),
            "business_summary": _safe(info, "longBusinessSummary"),
        },
        "size_and_price": {
            "current_price": _safe(info, "currentPrice"),
            "market_cap": _safe(info, "marketCap"),
            "enterprise_value": _safe(info, "enterpriseValue"),
            "shares_outstanding": _safe(info, "sharesOutstanding"),
            "float_shares": _safe(info, "floatShares"),
            "average_volume_10d": _safe(info, "averageDailyVolume10Day"),
            "beta": _safe(info, "beta"),
        },
        "valuation_multiples": {
            "trailing_pe": _safe(info, "trailingPE"),
            "forward_pe": _safe(info, "forwardPE"),
            "price_to_sales_ttm": _safe(info, "priceToSalesTrailing12Months"),
            "ev_to_ebitda": _safe(info, "enterpriseToEbitda"),
            "ev_to_revenue": _safe(info, "enterpriseToRevenue"),
            "peg_ratio": _safe(info, "pegRatio") or _safe(info, "trailingPegRatio"),
            "price_to_book": _safe(info, "priceToBook"),
        },
        "profitability_and_returns": {
            "gross_margin": _safe(info, "grossMargins"),
            "operating_margin": _safe(info, "operatingMargins"),
            "ebitda_margin": _safe(info, "ebitdaMargins"),
            "profit_margin": _safe(info, "profitMargins"),
            "return_on_assets": _safe(info, "returnOnAssets"),
            "return_on_equity": _safe(info, "returnOnEquity"),
        },
        "growth": {
            "revenue_growth_yoy": _safe(info, "revenueGrowth"),
            "earnings_growth_yoy": _safe(info, "earningsGrowth"),
            "earnings_quarterly_growth_yoy": _safe(info, "earningsQuarterlyGrowth"),
            "revenue_ttm": _safe(info, "totalRevenue"),
            "gross_profit_ttm": _safe(info, "grossProfits"),
            "ebitda_ttm": _safe(info, "ebitda"),
            "net_income_ttm": _safe(info, "netIncomeToCommon"),
        },
        "financial_health": {
            "total_cash": _safe(info, "totalCash"),
            "total_debt": _safe(info, "totalDebt"),
            "net_debt": (
                (_safe(info, "totalDebt") or 0) - (_safe(info, "totalCash") or 0)
                if _safe(info, "totalDebt") is not None and _safe(info, "totalCash") is not None
                else None
            ),
            "debt_to_equity": _safe(info, "debtToEquity"),
            "current_ratio": _safe(info, "currentRatio"),
            "quick_ratio": _safe(info, "quickRatio"),
            "free_cashflow": _safe(info, "freeCashflow"),
            "operating_cashflow": _safe(info, "operatingCashflow"),
            "book_value_per_share": _safe(info, "bookValue"),
        },
        "dividend_and_buybacks": {
            "dividend_yield": _safe(info, "dividendYield"),
            "dividend_rate": _safe(info, "dividendRate"),
            "payout_ratio": _safe(info, "payoutRatio"),
            "five_year_avg_dividend_yield": _safe(info, "fiveYearAvgDividendYield"),
        },
        "analyst_view": {
            "recommendation_key": _safe(info, "recommendationKey"),
            "recommendation_mean": _safe(info, "recommendationMean"),
            "number_of_analysts": _safe(info, "numberOfAnalystOpinions"),
            "target_mean_price": _safe(info, "targetMeanPrice"),
            "target_high_price": _safe(info, "targetHighPrice"),
            "target_low_price": _safe(info, "targetLowPrice"),
            "target_median_price": _safe(info, "targetMedianPrice"),
        },
        "ownership_and_short": {
            "held_by_insiders_pct": _safe(info, "heldPercentInsiders"),
            "held_by_institutions_pct": _safe(info, "heldPercentInstitutions"),
            "shares_short": _safe(info, "sharesShort"),
            "short_ratio": _safe(info, "shortRatio"),
            "short_percent_of_float": _safe(info, "shortPercentOfFloat"),
            "shares_short_prior_month": _safe(info, "sharesShortPriorMonth"),
        },
    }

    # Multi-year statements
    try:
        snapshot["income_statement_annual"] = _df_to_records(yt.financials, max_cols=4)
        snapshot["income_statement_quarterly"] = _df_to_records(yt.quarterly_financials, max_cols=6)
    except Exception:
        pass
    try:
        snapshot["balance_sheet_annual"] = _df_to_records(yt.balance_sheet, max_cols=4)
        snapshot["balance_sheet_quarterly"] = _df_to_records(yt.quarterly_balance_sheet, max_cols=4)
    except Exception:
        pass
    try:
        snapshot["cashflow_annual"] = _df_to_records(yt.cashflow, max_cols=4)
        snapshot["cashflow_quarterly"] = _df_to_records(yt.quarterly_cashflow, max_cols=4)
    except Exception:
        pass

    snapshot["price_stats_1y"] = _price_stats(yt)
    snapshot["technical_4h_rsi"] = _rsi_4h(ticker)
    snapshot["earnings_history"] = _earnings_history(yt)
    snapshot["upcoming_calendar"] = _calendar(yt)
    snapshot["analyst_actions"] = _recommendations(yt)
    snapshot["insider_activity"] = _insiders(yt)
    snapshot["holders"] = _holders(yt)
    snapshot["recent_news"] = _news(yt)

    peers = _peers_from_universe(ticker)
    snapshot["same_subcategory_peers"] = _peer_snapshot(peers)

    return snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    snap = gather_comprehensive(args.ticker.upper())
    indent = 2 if args.pretty else None
    json.dump(snap, sys.stdout, default=str, indent=indent)
    print()


if __name__ == "__main__":
    main()
