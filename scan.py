"""End-to-end scan orchestrator.

  python scan.py                        # full run with analysis
  python scan.py --skip-analysis        # data + dashboard only
  python scan.py --force-hit NVDA       # treat NVDA as a hit even if not oversold (dry-run analysis path)
  python scan.py --max-hits 3           # cap analyzed hits this run
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scripts.fetch_prices import fetch_4h_bars, drop_in_progress_bar
from scripts.compute_rsi import attach_rsi
from scripts.render_dashboard import render, md_to_html
from scripts.deep_dive import fetch_inline_fundamentals


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def flatten_universe(universe: dict) -> list[dict]:
    """[{ticker, name, note, sector}, ...] from the sector-keyed yaml."""
    rows = []
    for sector, items in universe["sectors"].items():
        for it in items:
            rows.append(
                {
                    "ticker": it["ticker"],
                    "name": it.get("name", it["ticker"]),
                    "note": it.get("note", ""),
                    "sector": sector,
                }
            )
    return rows


def build_scan_rows(
    flat_universe: list[dict],
    price_data: dict[str, dict],
    *,
    oversold: float,
    watch: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (all_rows, hits, watch_list).

    `price_data` is a dict {ticker -> {"closed": df_with_rsi, "live": df_with_rsi}}.
    'closed' has the in-progress bar dropped (signal source). 'live' includes the
    in-progress bar if one exists, for the "what RSI would be if bar closed now" view.
    """
    all_rows: list[dict] = []
    for u in flat_universe:
        t = u["ticker"]
        bundle = price_data.get(t)
        if bundle is None:
            all_rows.append(
                {
                    "ticker": t, "company": u["name"], "sector": u["sector"],
                    "price": None, "rsi": None, "bar_change_pct": None,
                    "live_price": None, "live_rsi": None, "live_bar_ts": None, "is_live": False,
                    "status": "error", "df": None,
                }
            )
            continue
        df = bundle["closed"]
        df_rsi = df.dropna(subset=["RSI_14"]) if df is not None and "RSI_14" in df.columns else None
        if df_rsi is None or df_rsi.empty:
            all_rows.append(
                {
                    "ticker": t, "company": u["name"], "sector": u["sector"],
                    "price": None, "rsi": None, "bar_change_pct": None,
                    "live_price": None, "live_rsi": None, "live_bar_ts": None, "is_live": False,
                    "status": "error", "df": None,
                }
            )
            continue
        prev = df_rsi.iloc[-2] if len(df_rsi) > 1 else None

        # Live view: most recent bar from the in-progress-included series.
        # This is what we display as "Price" and "RSI(14)" — the latest live values.
        live_df = bundle.get("live")
        live_rsi_series = live_df.dropna(subset=["RSI_14"]) if live_df is not None and "RSI_14" in live_df.columns else None
        if live_rsi_series is not None and not live_rsi_series.empty:
            live_last = live_rsi_series.iloc[-1]
            rsi = float(live_last["RSI_14"])
            price = float(live_last["Close"])
            live_ts = live_rsi_series.index[-1]
            is_live = live_ts > df_rsi.index[-1]  # newer than last closed
        else:
            last = df_rsi.iloc[-1]
            rsi = float(last["RSI_14"])
            price = float(last["Close"])
            live_ts = df_rsi.index[-1]
            is_live = False

        # Bar change: current live price vs the previous closed bar's close.
        change = ((price - prev["Close"]) / prev["Close"] * 100) if prev is not None else None
        status = "oversold" if rsi < oversold else "watch" if rsi < watch else "ok"

        all_rows.append(
            {
                "ticker": t,
                "company": u["name"],
                "sector": u["sector"],
                "price": price,
                "rsi": rsi,
                "bar_change_pct": float(change) if change is not None else None,
                "live_bar_ts": live_ts,
                "is_live": is_live,
                "status": status,
                "last_bar_ts": df_rsi.index[-1],
                "df": df,
            }
        )

    # Full scan rows: alphabetical by ticker (table is searchable/scannable).
    # Hits and watch list are sorted by RSI ascending so the most-oversold sits first
    # in those panels.
    all_rows.sort(key=lambda r: r["ticker"])
    by_rsi = sorted(all_rows, key=lambda r: (r["rsi"] if r["rsi"] is not None else 200))
    hits = [r for r in by_rsi if r["status"] == "oversold"]
    watch_list = [r for r in by_rsi if r["status"] == "watch"]
    return all_rows, hits, watch_list


def run_analysis_for_hit(row: dict, settings: dict, model: str) -> dict:
    """Calls the Claude API to produce why_it_fell + deep_dive for one hit."""
    from scripts.why_it_fell import analyze_why_it_fell
    from scripts.deep_dive import analyze_deep_dive

    out = {"why_it_fell": None, "why_it_fell_citations": [], "why_it_fell_error": None,
           "deep_dive": None, "deep_dive_error": None}

    df = row["df"]
    recent = df.dropna(subset=["RSI_14"]).tail(6)
    recent_bars = [
        {
            "ts": ts.strftime("%Y-%m-%d %H:%M ET"),
            "open": float(r["Open"]),
            "high": float(r["High"]),
            "low": float(r["Low"]),
            "close": float(r["Close"]),
            "volume": float(r["Volume"]),
            "rsi": float(r["RSI_14"]),
        }
        for ts, r in recent.iterrows()
    ]

    if settings["analysis"]["why_it_fell"]["enabled"]:
        try:
            res = analyze_why_it_fell(
                row["ticker"], row["company"], recent_bars,
                model=model,
                max_tokens=settings["analysis"]["max_tokens"],
                web_search_max_uses=settings["analysis"]["why_it_fell"]["web_search_max_uses"],
            )
            out["why_it_fell"] = res["text"]
            out["why_it_fell_citations"] = res["citations"]
        except Exception as e:
            out["why_it_fell_error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    if settings["analysis"]["deep_dive"]["enabled"]:
        try:
            res = analyze_deep_dive(
                row["ticker"], row["company"],
                model=model,
                max_tokens=settings["analysis"]["max_tokens"],
            )
            out["deep_dive"] = res["text"]
        except Exception as e:
            out["deep_dive_error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-analysis", action="store_true", help="Skip Claude API calls")
    ap.add_argument("--force-hit", action="append", default=[], help="Force ticker into hits list (for testing analysis path)")
    ap.add_argument("--max-hits", type=int, help="Override settings.analysis.max_hits_to_analyze")
    ap.add_argument("--output", type=str, help="Override output HTML path")
    args = ap.parse_args()

    settings = load_yaml(ROOT / "config" / "settings.yaml")
    universe = load_yaml(ROOT / "config" / "universe.yaml")
    flat = flatten_universe(universe)
    tickers = [u["ticker"] for u in flat]

    print(f"[1/4] Fetching 4h bars for {len(tickers)} tickers...")
    raw = fetch_4h_bars(tickers, period=settings["prices"]["period"])

    print(f"[2/4] Computing RSI (closed + live views)...")
    period = settings["rsi"]["period"]
    price_data: dict[str, dict] = {}
    for t, df_raw in raw.items():
        if df_raw is None or df_raw.empty:
            continue
        df_closed = drop_in_progress_bar(df_raw)
        if df_closed.empty:
            continue
        price_data[t] = {
            "closed": attach_rsi(df_closed, period=period),
            "live": attach_rsi(df_raw, period=period),
        }

    all_rows, hits, watch_list = build_scan_rows(
        flat, price_data,
        oversold=settings["rsi"]["oversold_threshold"],
        watch=settings["rsi"]["watch_threshold"],
    )

    print(f"      Fetching inline fundamentals ({len(tickers)} tickers)...")
    inline_fund = fetch_inline_fundamentals(tickers)

    # Force hits if requested (test path)
    if args.force_hit:
        forced = []
        for t in args.force_hit:
            match = next((r for r in all_rows if r["ticker"] == t), None)
            if match and match not in hits:
                match["status"] = "oversold"
                forced.append(match)
        hits = forced + hits

    print(f"      {len(hits)} oversold, {len(watch_list)} watch, {len(all_rows) - len(hits) - len(watch_list)} ok")

    # --- Analysis ---
    do_analysis = not args.skip_analysis
    if do_analysis and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[3/4] ANTHROPIC_API_KEY not set — skipping analysis (run with --skip-analysis to silence).")
        do_analysis = False
    if not hits:
        do_analysis = False

    max_hits = args.max_hits if args.max_hits is not None else settings["analysis"]["max_hits_to_analyze"]
    analyzed_hits = hits[:max_hits] if do_analysis else []

    analysis_results: dict[str, dict] = {}
    if do_analysis:
        print(f"[3/4] Running Claude analysis on {len(analyzed_hits)} hits (model={settings['analysis']['model']})...")
        for i, h in enumerate(analyzed_hits, 1):
            print(f"      ({i}/{len(analyzed_hits)}) {h['ticker']}")
            analysis_results[h["ticker"]] = run_analysis_for_hit(h, settings, settings["analysis"]["model"])
    else:
        print(f"[3/4] Analysis skipped.")

    # --- Render ---
    print(f"[4/4] Rendering dashboard...")
    now_utc = datetime.now(tz=ZoneInfo("UTC"))
    now_pt = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    PT = ZoneInfo("America/Los_Angeles")
    latest_ts = max((r["last_bar_ts"] for r in all_rows if r.get("last_bar_ts") is not None), default=None)

    rendered_hits = []
    for h in hits:
        a = analysis_results.get(h["ticker"], {})
        skip_msg_why = None
        skip_msg_dd = None
        if h["ticker"] not in analysis_results:
            if not do_analysis:
                skip_msg_why = f"Open this repo in Claude Code and run <code>/why-fell {h['ticker']}</code> locally to generate this section."
                skip_msg_dd = f"Open this repo in Claude Code and run <code>/analyze-stock {h['ticker']}</code> locally to generate this section."
            else:
                skip_msg_why = skip_msg_dd = f"Hit beyond max_hits_to_analyze ({max_hits})."
        else:
            if a.get("why_it_fell_error"):
                skip_msg_why = f"Error: {a['why_it_fell_error']}"
            if a.get("deep_dive_error"):
                skip_msg_dd = f"Error: {a['deep_dive_error']}"

        df = h["df"]
        recent = df.dropna(subset=["RSI_14"]).tail(6)
        move_5bar = (recent["Close"].iloc[-1] - recent["Close"].iloc[0]) / recent["Close"].iloc[0] * 100

        rendered_hits.append(
            {
                "ticker": h["ticker"],
                "company": h["company"],
                "sector": h["sector"],
                "price": h["price"],
                "rsi": h["rsi"],
                "move_5bar_pct": float(move_5bar),
                "bar_human": h["live_bar_ts"].tz_convert(PT).strftime("%Y-%m-%d %H:%M PT"),
                "why_it_fell_html": md_to_html(a.get("why_it_fell") or ""),
                "why_it_fell_citations": a.get("why_it_fell_citations", []),
                "why_it_fell_skip_reason": skip_msg_why,
                "deep_dive_html": md_to_html(a.get("deep_dive") or ""),
                "deep_dive_skip_reason": skip_msg_dd,
            }
        )

    rendered_watch = [
        {
            "ticker": w["ticker"], "company": w["company"],
            "rsi": w["rsi"], "price": w["price"],
        }
        for w in watch_list
    ]

    rsi_values = [r["rsi"] for r in all_rows if r["rsi"] is not None]
    median_rsi = statistics.median(rsi_values) if rsi_values else None

    # Live bar timestamp: the most recent in-progress bar across all tickers
    live_ts_candidates = [r["live_bar_ts"] for r in all_rows if r.get("is_live") and r.get("live_bar_ts") is not None]
    live_bar_ts = max(live_ts_candidates) if live_ts_candidates else None
    has_live = live_bar_ts is not None

    context = {
        "title": settings["dashboard"]["title"],
        "run_ts_human_pt": now_pt.strftime("%Y-%m-%d %H:%M") + " PT",
        "run_ts_iso": now_utc.isoformat(timespec="seconds"),
        "latest_bar_human": latest_ts.tz_convert(PT).strftime("%Y-%m-%d %H:%M PT") if latest_ts is not None else "—",
        "live_bar_human": live_bar_ts.tz_convert(PT).strftime("%Y-%m-%d %H:%M PT") if live_bar_ts is not None else None,
        "has_live": has_live,
        "universe_size": len(flat),
        "oversold_threshold": settings["rsi"]["oversold_threshold"],
        "watch_threshold": settings["rsi"]["watch_threshold"],
        "rsi_period": settings["rsi"]["period"],
        "hits": rendered_hits,
        "watch": rendered_watch,
        "rows": [
            {
                "ticker": r["ticker"],
                "company": r["company"],
                "sector": r["sector"],
                "price": r["price"],
                "rsi": r["rsi"],
                "bar_change_pct": r["bar_change_pct"],
                "status": r["status"],
                "market_cap": inline_fund.get(r["ticker"], {}).get("market_cap"),
                "pe": inline_fund.get(r["ticker"], {}).get("trailing_pe"),
                "peg": inline_fund.get(r["ticker"], {}).get("peg_ratio"),
                "beta": inline_fund.get(r["ticker"], {}).get("beta"),
            }
            for r in all_rows
        ],
        "median_rsi": median_rsi,
        "analysis_model": settings["analysis"]["model"] if do_analysis else None,
    }

    out_dir = ROOT / settings["dashboard"]["output_dir"]
    out_path = Path(args.output) if args.output else out_dir / f"dashboard-{now.strftime('%Y-%m-%d-%H%M')}.html"
    render(context, template_dir=ROOT / "templates", output_path=out_path)
    print(f"      wrote {out_path}")
    print(f"\nDone. Open: {out_path}")


if __name__ == "__main__":
    main()
