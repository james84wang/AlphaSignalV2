#!/usr/bin/env python
"""Demo: fetch 5 years of daily bars for AAPL, MSFT, NVDA and cache as Parquet.

Run from the repo root:
    python scripts/fetch_demo.py

Second run is instant — data is served entirely from the Parquet cache.
"""
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Ensure the repo root is on sys.path so `backend` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.data.cache import ParquetCache
from backend.app.data.provider import ProviderError
from backend.app.data.yfinance_provider import YFinanceProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_demo")

SYMBOLS = ["AAPL", "MSFT", "NVDA"]
YEARS_BACK = 5
END = date.today()
START = END - timedelta(days=365 * YEARS_BACK)


def main() -> None:
    provider = YFinanceProvider()
    cache = ParquetCache(provider)

    logger.info("Fetching %d years of bars (%s → %s) for %s", YEARS_BACK, START, END, SYMBOLS)
    logger.info("Cache dir: %s", cache.cache_path("AAPL").parent)

    for symbol in SYMBOLS:
        t0 = time.perf_counter()
        try:
            df = cache.get_daily_bars(symbol, START, END)
            elapsed = time.perf_counter() - t0
            logger.info(
                "[%s] %d bars  first=%s  last=%s  (%.2fs)",
                symbol,
                len(df),
                df.index.min().date(),
                df.index.max().date(),
                elapsed,
            )
            print(f"\n── {symbol} (last 5 rows) ──")
            print(df.tail())
            print(f"Cache file: {cache.cache_path(symbol)}")
        except ProviderError as exc:
            logger.error("[%s] Failed: %s", symbol, exc)

    print("\nRun the script again — the second run should be near-instant from cache.")


if __name__ == "__main__":
    main()
