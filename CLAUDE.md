# CLAUDE.md — AlphaSignal Project Brief
# This file is read automatically by Claude Code at the start of every session.

## What we're building
AlphaSignal: a **personal-use** (not commercial) local web app for analysing US
equities and building/tuning a trading strategy. It runs daily over a configurable
universe of US stocks, computes a composite reversal/momentum signal per stock per
day, lets the user re-tune the score weights of each indicator, and backtests the
tuned strategy over historical data.
Design and UX inspiration: TradingView (dark theme, clean charting layout).

## How to start the app (one command)
```bash
cd /Users/jameswang/Documents/Claude/Code/AlphaSignalV2
scripts/launch.sh            # auto-builds frontend, starts backend, opens Chrome
scripts/launch.sh --rebuild  # force frontend rebuild
scripts/launch.sh --no-build # skip build (faster restart)
```
Backend runs at http://localhost:8000. Frontend is served from backend/app/static/.

## Non-negotiable ground rules
- Personal research only. No accounts, no auth, no multi-tenant, no cloud deploy.
- Strategy logic is FULLY SPECIFIED in `trading_strategy_spec.md`. Treat it as the
  source of truth. If config.yaml and the spec disagree, the spec wins.
- All strategy weights, thresholds and scoring tables live in `config.yaml`. NEVER
  hard-code a weight or score in a function. Read them from config.
- No look-ahead bias, ever. Any signal for bar T must use ONLY data available at the
  close of bar T (or earlier). Backtests that peek at future bars are a critical bug.
- Data may be delayed up to 1 hour — this is NOT a day-trading tool. Daily bars only.

## Tech stack (do not change without asking)
- Backend:  Python 3.11+, FastAPI, uvicorn, pandas, numpy, pandas-ta, yfinance,
            pydantic v2, PyYAML, SQLAlchemy (SQLite), pyarrow, httpx, apscheduler.
            Tests: pytest.
- Frontend: React 18 + Vite + TypeScript, Tailwind CSS,
            lightweight-charts (TradingView candlestick/line charts),
            TanStack Query (data fetching), react-router-dom, xlsx (SheetJS).
            Tests: Vitest.
- Tooling:  ruff (Python lint+format); eslint/prettier (TypeScript).

## Repo layout
```
AlphaSignalV2/
  CLAUDE.md                    # this file — auto-loaded by Claude Code
  RECOVERY.txt                 # full disaster-recovery / rebuild guide
  config.yaml                  # ALL weights, thresholds, scoring tables
  trading_strategy_spec.md     # strategy source of truth — read for scoring changes
  pyproject.toml               # Python deps & tool config
  scripts/
    launch.sh                  # start everything (builds frontend + starts backend)
    run_daily.py               # CLI daily signal run
  backend/
    app/
      main.py                  # FastAPI entry point; serves frontend static files
      config.py                # loads & validates config.yaml
      api/
        signals.py             # GET  /api/signals
        runs.py                # POST /api/runs/daily, GET /api/runs/daily/{job_id}
        backtest.py            # POST /api/backtest, GET /api/backtest/{job_id}
        symbols.py             # GET  /api/symbols/{symbol}/bars|signal
        config_routes.py       # GET/PUT /api/config/{strategy}
        market.py              # GET  /api/market/overview
        watchlist.py           # GET/POST/DELETE /api/watchlist
        schedule.py            # GET/PUT /api/schedule
        inverse_etfs.py        # GET  /api/inverse-etfs
      data/
        universe.py            # fetch_sp500/sp400/sp600/sp1000_symbols(); Universe class
        market_overview.py     # index quotes + CNN Fear & Greed (15-min cache)
        yfinance_provider.py   # yfinance data adapter
        cache.py               # ParquetCache — local price cache
        inverse_etfs.py        # load inverse-ETF map from CSV
      indicators/              # pure functions: ema, macd, rsi, pivots, candlestick, sr
      scoring/                 # composite.py + one module per component + regime.py
      backtest/                # engine.py + metrics.py
      db/
        models.py              # SQLAlchemy models: Run, Signal, WatchlistEntry
        backtest_models.py     # BacktestRun model
      static/                  # compiled frontend (gitignored; rebuilt by launch.sh)
    tests/                     # pytest — mirrors app/ structure
  frontend/
    src/
      lib/
        api.ts                 # all fetch functions (typed)
        types.ts               # all TypeScript interfaces
        exportSettings.ts      # Excel export utility (SheetJS)
      components/
        MarketOverview.tsx     # index tiles with sparklines + Fear & Greed gauge
        SignalBadge.tsx        # coloured signal label
        WatchlistEditor.tsx    # add/remove watchlist symbols
        InverseEtfEditor.tsx   # read-only inverse-ETF table
        ScheduleToggle.tsx     # daily run schedule toggle
        Layout.tsx             # sidebar navigation
      pages/
        Dashboard.tsx          # market overview + run buttons + 3 signal sections
        SymbolDetail.tsx       # chart + full score audit
        Backtest.tsx           # backtest form + equity curve + trade log
        Settings.tsx           # weights, thresholds, scoring tables, export button
    package.json
  data/                        # gitignored (auto-created)
    signals.db                 # SQLite: runs, signals, watchlist, backtest results
    watchlist.csv              # user stock watchlist (seeded to DB on startup)
    inverse_etfs.csv           # symbol → inverse ETF mapping
    sp500.csv / sp400.csv / sp600.csv  # cached index constituent lists
    cache/                     # Parquet price cache per symbol
```

## Key API endpoints (quick reference)
```
GET  /api/signals?universe=combined          Latest ranked signals
POST /api/runs/daily                         Trigger a signal scan
GET  /api/runs/daily/{job_id}               Poll scan status
POST /api/backtest                           Start a backtest
GET  /api/backtest/{job_id}                 Poll / retrieve backtest result
GET  /api/symbols/{symbol}/bars?range=1y    OHLCV bars
GET  /api/symbols/{symbol}/signal?date=X   Full score audit
GET  /api/config/{strategy}                 Load long|short config
PUT  /api/config/{strategy}                 Save weights/thresholds/scoring
GET  /api/market/overview                   Index quotes + Fear & Greed
GET  /api/watchlist                         List watchlist
POST /api/watchlist                         Add symbol
DEL  /api/watchlist/{symbol}               Remove symbol
GET  /api/inverse-etfs                      Inverse-ETF map
GET  /api/schedule                          Daily schedule status
PUT  /api/schedule                          Enable/disable schedule
GET  /health                                Health check
```

Valid universe values: `watchlist` | `sp500` | `midcap` | `smallcap` | `combined`
Valid strategy values: `long` | `short`

## Scoring architecture (quick reference)
- 8 components, each returns a sub-score in [-100, +100]:
  candlestick, p3 (3-bar pattern), p5 (5-bar pattern), volume,
  ema, sr (support/resistance), macd, rsi
- Composite = Σ (sub_score × weight/100), then regime gate applied
- Regime gate (200-EMA slope): long_allowed, short_allowed
- Signal labels: Strong Buy (≥85) | Buy (≥70) | Hold | Sell (≤-70) | Strong Sell (≤-85)
- All thresholds and weights are in config.yaml under strategies.long / strategies.short

## Coding conventions
- Python: type hints everywhere. Pure functions for indicators & scoring.
  Docstrings cite the spec section (e.g. "implements spec §4.5 EMA system").
- Determinism: same input data + same config = same output. No randomness.
- Errors: data-layer failures must be caught, logged, and never silently return
  wrong numbers. Missing/short series = "insufficient data", not a 0 score.
- Frontend: all API calls go through lib/api.ts. All types defined in lib/types.ts.
  TanStack Query for all server state. No direct fetch() calls in components.

## How to run tests
```bash
pytest -q                        # backend tests
cd frontend && npm test          # frontend tests
```

## How to rebuild frontend only
```bash
cd frontend && pnpm run build
```
(The backend serves directly from `frontend/dist/` — no copy step needed.)

## Definition of Done

Every change that affects **scope, data sources, strategy logic, or backtest behaviour**
MUST update `docs/ABOUT.md` (relevant tab) and add a dated entry to the Changelog tab
in the same commit. This keeps the About section current without manual auditing.

Specifically:
- New or changed data source → update Tab 1 (Overview & Scope, Data Sources table)
- Changed strategy weights/thresholds/regime logic → update Tab 2 (Strategy Details)
- Changed backtest parameters, fee model, or benchmark → update Tab 3 (Backtest Details)
- Any of the above → add a dated entry at the top of Tab 4 (Changelog)

## Owner profile
- Beginner programmer (≈2/10). Always explain manual steps as numbered,
  copy-paste-able Terminal commands.
- Make reasonable assumptions and proceed; state them.
- Ask before: installing global tools, deleting files, network actions needing API keys.

## GitHub repository
https://github.com/james84wang/AlphaSignalV2
Push changes: git add -A && git commit -m "description" && git push
