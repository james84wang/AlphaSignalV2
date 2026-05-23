"""Parquet-based cache for daily OHLCV bars.

Cache layout:
    data/
      bars/
        AAPL.parquet
        MSFT.parquet
        ...

On a cache hit the file is read and any missing date range is fetched from the
provider and merged in.  A force_refresh=True call discards the file and
re-fetches everything from the provider.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .provider import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "bars"


class ParquetCache:
    """Read-through Parquet cache that sits in front of any MarketDataProvider.

    Usage:
        provider = YFinanceProvider()
        cache = ParquetCache(provider)
        df = cache.get_daily_bars("AAPL", date(2020, 1, 1), date.today())
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        cache_dir: Path | str | None = None,
    ) -> None:
        self._provider = provider
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ParquetCache using dir: %s", self._cache_dir)

    def _cache_path(self, symbol: str) -> Path:
        return self._cache_dir / f"{symbol.upper()}.parquet"

    def _read_cache(self, symbol: str) -> pd.DataFrame | None:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            df.index.name = "date"
            logger.debug("[%s] Cache hit: %d bars from %s", symbol, len(df), path)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] Cache read failed (%s) — will re-fetch", symbol, exc)
            return None

    def _write_cache(self, symbol: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        path = self._cache_path(symbol)
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        logger.debug("[%s] Wrote %d bars to %s", symbol, len(df), path)

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Return OHLCV bars, fetching only the missing portion from the provider.

        With force_refresh=True, the existing cache file is deleted and all data
        is re-fetched.
        """
        symbol = symbol.upper()

        if force_refresh:
            path = self._cache_path(symbol)
            if path.exists():
                path.unlink()
                logger.info("[%s] Cache cleared for force refresh", symbol)

        cached = self._read_cache(symbol)

        if cached is None:
            # No cache at all — fetch entire range.
            logger.info("[%s] No cache — fetching %s → %s", symbol, start, end)
            fetched = self._provider.get_daily_bars(symbol, start, end)
            self._write_cache(symbol, fetched)
            return _slice(fetched, start, end)

        # Determine what's missing.
        cached_start = cached.index.min().date()
        cached_end = cached.index.max().date()

        frames: list[pd.DataFrame] = [cached]

        # Allow a 4-day buffer to absorb weekends and market holidays before
        # deciding the cache needs extension (avoids spurious weekend fetches).
        _BUFFER = timedelta(days=4)

        if start < cached_start - _BUFFER:
            fetch_end = cached_start - timedelta(days=1)
            logger.info("[%s] Fetching missing early range %s → %s", symbol, start, fetch_end)
            try:
                early = self._provider.get_daily_bars(symbol, start, fetch_end)
                if not early.empty:
                    frames.insert(0, early)
            except ProviderError as exc:
                logger.warning("[%s] Could not extend early range: %s", symbol, exc)

        if end > cached_end:
            fetch_start = cached_end + timedelta(days=1)
            logger.info("[%s] Fetching missing late range %s → %s", symbol, fetch_start, end)
            try:
                late = self._provider.get_daily_bars(symbol, fetch_start, end)
                if not late.empty:
                    frames.append(late)
            except ProviderError as exc:
                logger.warning("[%s] Could not extend late range: %s", symbol, exc)

        if len(frames) > 1:
            merged = pd.concat(frames)
            merged = merged[~merged.index.duplicated(keep="last")]
            merged.sort_index(inplace=True)
            self._write_cache(symbol, merged)
            return _slice(merged, start, end)

        return _slice(cached, start, end)

    def cache_path(self, symbol: str) -> Path:
        """Return the Parquet file path for *symbol* (file may not exist yet)."""
        return self._cache_path(symbol.upper())


def _slice(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Return rows where index is between *start* and *end* (both inclusive)."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    return df.loc[(df.index >= s) & (df.index <= e)]
