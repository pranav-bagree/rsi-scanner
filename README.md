# RSI Oversold Scanner

Twice-daily scan of 48 AI-infrastructure stocks for 4h-RSI oversold signals. The data pipeline runs on GitHub Actions and publishes a dashboard to GitHub Pages. The qualitative analysis (why a stock fell, fundamental deep-dive) is intentionally **not** run in CI — it's invoked locally from Claude Code via skills, on demand, against any ticker you want.

See [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) for the original design brief and locked decisions.

## Architecture (split pipeline)

```
                  ┌─────────────────────────────────────┐
                  │ GitHub Actions (cron, 2x daily)     │
                  │   - fetch 4h bars from yfinance     │
                  │   - compute Wilder RSI(14)          │
                  │   - render HTML dashboard           │
                  │   - publish to GitHub Pages         │
                  └─────────────────────────────────────┘
                                  │
                                  ▼
                  https://<user>.github.io/rsi-scanner/

                  ┌─────────────────────────────────────┐
                  │ You (locally in Claude Code)        │
                  │   /analyze-stock TICKER             │
                  │   /why-fell TICKER                  │
                  └─────────────────────────────────────┘
```

**Why split?** The Claude analysis requires API credentials. This project uses Claude Code skills locally (which use your existing Claude Code auth) rather than a separate Anthropic API key in CI.

## Set up GitHub Actions + Pages

1. Create a private repo on GitHub (e.g. `rsi-scanner`).
2. Push this project to it:
   ```bash
   cd ~/Desktop/rsi-scanner
   git init && git add -A && git commit -m "Initial commit"
   git remote add origin git@github.com:<your-username>/rsi-scanner.git
   git branch -M main
   git push -u origin main
   ```
3. In GitHub: **Settings → Pages**. Under **Build and deployment → Source**, pick **GitHub Actions**.
4. In GitHub: **Actions** tab. The first scheduled run will happen at the next cron tick — or click **Daily 4h RSI scan → Run workflow** to trigger it immediately.
5. Once the workflow succeeds, your dashboard is live at `https://<your-username>.github.io/rsi-scanner/`.

### Visibility note

- Free GitHub plan: private repo + Pages → the dashboard URL is **publicly accessible** (URL is unguessable but unauthenticated visitors can view it). The source code stays private.
- Want auth-gated Pages? Upgrade to GitHub Pro ($4/mo) and set **Settings → Pages → Visibility → Private**.

## Use the Claude Code skills

The repo ships with three skills under `.claude/skills/`. They are auto-discovered by Claude Code when you `cd` into this repo. Run them from inside a Claude Code session:

- `/analyze-stock NVDA` — quick fundamental deep-dive (business, valuation, financial health, growth, risks, bull/bear, bottom line). ~5–10 min.
- `/why-fell NET` — explains a recent drop using a web search across the last 5 trading days, framed by recent 4h price/RSI action. ~3–5 min.
- `/equity-research NVDA` — **full professional research report**: executive summary with rating and target range, multi-year financials review, peer comparables table, capital allocation analysis, catalyst calendar, three-scenario valuation (bull/base/bear), technical context, insider/institutional activity, and explicit position-sizing guidance. Saves to `output/research/{TICKER}-{date}.md`. ~10–20 min.

To make them globally available across all your Claude Code sessions:

```bash
mkdir -p ~/.claude/skills
cp -r .claude/skills/* ~/.claude/skills/
```

## Local dev

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Render the dashboard locally (data pipeline only):
.venv/bin/python scan.py --skip-analysis

# Same path GH Actions uses (writes to public/index.html):
.venv/bin/python scan.py --skip-analysis --output public/index.html

# Force a ticker into the hits list to preview the analysis-prompt UI:
.venv/bin/python scan.py --skip-analysis --force-hit APH
```

## Signal logic

- Pulls 4h OHLCV from yfinance using its native `interval='4h'` (9:30 / 13:30 ET buckets, TradingView convention).
- Drops the in-progress afternoon bar when run mid-session — signals fire only on closed bars.
- 14-period Wilder RSI on the 4h close series.
- **Oversold:** most recent closed RSI < 25 (configurable in `config/settings.yaml`).
- **Watch:** RSI in 25–35.

## Project layout

```
rsi-scanner/
├── .github/workflows/daily-scan.yml   # GH Actions cron + Pages deploy
├── .claude/skills/
│   ├── analyze-stock/SKILL.md         # local Claude Code skill: quick fundamental deep-dive
│   ├── why-fell/SKILL.md              # local Claude Code skill: news-driven cause
│   └── equity-research/SKILL.md       # local Claude Code skill: full sell-side research report
├── config/
│   ├── universe.yaml                  # 48 tickers in 12 subcategories
│   └── settings.yaml                  # thresholds, periods, paths
├── scripts/
│   ├── fetch_prices.py                # batched yfinance 4h pulls
│   ├── compute_rsi.py                 # Wilder RSI
│   ├── render_dashboard.py            # Jinja2 -> HTML
│   ├── equity_research.py             # comprehensive ticker snapshot (used by /equity-research)
│   ├── why_it_fell.py                 # (unused in CI — kept for reference / API-key path)
│   └── deep_dive.py                   # gather_fundamentals() reused by /analyze-stock skill
├── templates/dashboard.html.j2
├── public/                            # built by GH Actions for Pages (also writable locally)
├── output/                            # local scan outputs (gitignored)
├── scan.py                            # orchestrator
├── requirements.txt
└── PROJECT_HANDOFF.md
```

## Scheduling details

Hourly during US trading hours, Monday–Friday. Single cron entry: `5 14-21 * * 1-5` (UTC).

UTC 14:05–21:05 maps to:
- **EDT** (Mar–Nov): 10:05 ET → 17:05 ET (one wasteful run after market close)
- **EST** (Nov–Mar): 09:05 ET → 16:05 ET (one wasteful run before market open)

Either way, all 7 trading hours plus the two 4h bar closes (13:30 ET and 16:00 ET) are covered with a 5-minute buffer for data settling. Extra runs are idempotent — they just regenerate the same dashboard.

## Validation

The 4h RSI methodology was cross-checked against TradingView on NET (Cloudflare) using its 2026-05-08 earnings drop. yfinance's native 4h interval produces bar-for-bar identical OHLCV to a 1h→4h resample. See [`net_rsi_native4h.py`](net_rsi_native4h.py) for the standalone single-ticker demo.
