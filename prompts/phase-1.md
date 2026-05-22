# PHASE 1 — Data layer (fetch, cache, watchlist/universe)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-1.md and execute it. Stop and report when done.

Read CLAUDE.md. We're building the DATA LAYER for AlphaSignal. Do not touch scoring yet.

GOAL
A reliable, swappable way to get daily OHLCV bars for US stocks, cached locally, plus
universe/watchlist management.

BUILD
1. backend/app/data/provider.py: an abstract `MarketDataProvider` interface with methods:
   get_daily_bars(symbol, start, end) -> DataFrame[date,open,high,low,close,volume],
   get_latest_quote(symbol), is_trading_day(date).
2. backend/app/data/yfinance_provider.py: implement the interface using yfinance as the
   PRIMARY source. Add retries with backoff, basic validation (monotonic dates, no NaNs
   in OHLC, positive volume), and clear logging. yfinance is unofficial and may break —
   handle failures gracefully and surface them.
3. backend/app/data/finnhub_provider.py: a SECONDARY adapter stub for quotes/earnings.
   Read the API key from env var FINNHUB_API_KEY. If absent, disable cleanly.
4. backend/app/data/cache.py: Parquet cache under data/ keyed by symbol. On request,
   serve from cache and only fetch missing/newer bars. Add a force-refresh option.
5. backend/app/data/universe.py: load a universe from a CSV (symbol,exchange). Provide a
   built-in S&P 500 list fetched once and cached. Support a user watchlist file
   data/watchlist.csv. Universe is configurable in config.yaml (default: {{UNIVERSE}}).
6. Tests in backend/tests/data/: mock the network; test cache hit/miss, validation,
   and graceful failure when the provider errors. NO real network calls in tests.

ACCEPTANCE
- I can run a small script that fetches {{BACKTEST_YEARS}} years of daily bars for AAPL,
  MSFT, NVDA and saves them to Parquet, then re-runs instantly from cache.
- Tests pass with no network access.

MANUAL STEPS FOR JAMES
1. Tell me if/where to get a free Finnhub key (https://finnhub.io) and exactly how to
   put it in a .env file. 2. Show me how to create data/watchlist.csv with 3 example rows.

REPORT BACK
Show me a sample of cached AAPL data and the cache file location. Flag any yfinance
reliability concerns you hit. Do NOT start Phase 2.
