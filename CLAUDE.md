# CLAUDE.md — AlphaSignal Project Brief

## What we're building
AlphaSignal: a **personal-use** (not commercial) desktop/web app for analysing US
equities and building/tuning a trading strategy. It runs daily over a watchlist of
US stocks, computes a composite reversal/momentum signal per stock per day, lets the
user re-tune the score weights of each indicator, and backtests the tuned strategy
over historical data. Design and UX inspiration: TradingView (charting, clean layout).

## Non-negotiable ground rules
- This is for ONE user (the owner), personal research only. No accounts, no auth, no
  multi-tenant, no cloud deploy required. Runs locally.
- The strategy logic is FULLY SPECIFIED in `trading_strategy_spec.md` and
  `trading_strategy_template.xlsx` (repo root). Treat the spec as the source of truth.
  If the two disagree, the .md spec wins; flag the discrepancy in your report.
- All strategy weights, thresholds and scoring tables live in `config.yaml`. NEVER
  hard-code a weight or score in a function. Read them from config.
- Data may be delayed up to 1 hour — this is NOT a day-trading tool. Daily bars only for v1.
- No look-ahead bias, ever. Any signal for bar T must use ONLY data available at the
  close of bar T (or earlier). Backtests that peek at future bars are a critical bug.

## Tech stack (do not change without asking)
- Backend: Python 3.11+, FastAPI, pandas, numpy, pandas-ta (or ta), yfinance, pydantic,
  PyYAML, SQLAlchemy (SQLite), pyarrow (Parquet). Tests: pytest.
- Frontend: React + Vite + TypeScript, Tailwind CSS, lightweight-charts (TradingView),
  TanStack Query for data fetching. Tests: Vitest.
- Tooling: ruff (lint+format) for Python; eslint/prettier for TS.

## Repo layout (create/maintain exactly this)
alphasignal/
  CLAUDE.md                  # this file
  README.md                  # how to install & run (keep updated)
  config.yaml                # all weights/thresholds/scoring tables
  pyproject.toml             # python deps & tool config
  trading_strategy_spec.md   # strategy source of truth
  trading_strategy_template.xlsx
  data/                      # local cache (gitignored)
  scripts/                   # run_daily.py, dev launchers
  backend/
    app/
      main.py                # FastAPI entry
      config.py              # loads & validates config.yaml
      api/                   # route modules
      data/                  # provider abstraction + adapters + cache
      indicators/            # pure functions: ema, macd, rsi, pivots, candlestick, sr
      scoring/               # one module per component + regime.py + composite.py
      backtest/              # engine.py + metrics.py
      db/                    # sqlite models + parquet helpers
    tests/                   # pytest, mirrors app/ structure
  frontend/
    src/
      assets/                # logo.svg goes here
      lib/                   # api client, chart helpers, types
      components/
      pages/
    package.json

## Coding conventions
- Python: type hints everywhere; pure functions for indicators & scoring (input = a
  pandas DataFrame slice, output = a number or small dict). Docstrings cite the spec
  section they implement (e.g. "implements spec §4.5 EMA system").
- Every scoring component returns a sub-score in [-100, +100]. The composite engine
  applies weight/100 and the regime gate exactly as spec §5 describes.
- Determinism: same input data + same config = same output. No randomness in scoring.
- Errors: data-layer failures must be caught, logged, retried, and never silently
  return wrong numbers. A missing/short series = "insufficient data", not a 0 score.

## Definition of Done (every phase)
1. Code runs with a single documented command.
2. Tests pass (`pytest -q` for backend; `npm test` for frontend).
3. README updated with any new run/setup steps.
4. No look-ahead bias introduced (state how you verified).
5. You report: what you built, how to run it, what you assumed, what's still open.

## How to treat me (the owner)
- I'm a beginner programmer (≈2/10). Explain any manual step I must take in plain,
  numbered, copy-paste-able instructions. Tell me exactly what to type and where.
- Make reasonable assumptions and proceed; state them. Don't ask many questions upfront.
- Ask me to approve before: installing global tools, deleting files, or any network
  action that needs an API key.

## Multi-session rule (important)
Multiple Claude Code sessions may work on this repo in parallel via git worktrees.
- ONLY edit files inside the directory/module you've been assigned for this session.
- Do NOT edit shared files (`config.yaml`, `CLAUDE.md`, `pyproject.toml`) unless this
  session is explicitly the owner of that file. If you need a change there, write the
  request into `SHARED_CHANGES.md` instead and tell me.
- Build against the documented API contract in `API_CONTRACT.md`; don't change it
  unilaterally.
