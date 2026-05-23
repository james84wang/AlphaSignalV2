"""Abstract interface for market data providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

import pandas as pd


class MarketDataProvider(ABC):
    """Swappable interface for fetching OHLCV bars and quotes.

    All implementations must return DataFrames with a DatetimeIndex (tz-naive, daily)
    and columns: open, high, low, close, volume (all float64 except volume int64).
    """

    @abstractmethod
    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return OHLCV bars for *symbol* from *start* to *end* (both inclusive).

        Returns a DataFrame indexed by date with columns:
            open, high, low, close (float64), volume (int64).
        Raises ProviderError on unrecoverable failure.
        """

    @abstractmethod
    def get_latest_quote(self, symbol: str) -> dict:
        """Return the latest available quote for *symbol*.

        Returns a dict with at minimum: symbol, price, timestamp.
        Raises ProviderError on failure.
        """

    @abstractmethod
    def is_trading_day(self, check_date: date) -> bool:
        """Return True when *check_date* is a US market trading day."""


class ProviderError(Exception):
    """Raised when a data provider cannot fulfil a request."""


def validate_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Validate and clean a raw OHLCV DataFrame.

    Checks:
    - Index is monotonically increasing dates.
    - No NaNs in open, high, low, close columns.
    - Volume is positive (strictly > 0).

    Returns the validated DataFrame.  Raises ProviderError with a clear message
    on any violation.
    """
    if df.empty:
        return df

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ProviderError(f"[{symbol}] Missing columns: {missing}")

    if not df.index.is_monotonic_increasing:
        raise ProviderError(f"[{symbol}] Index dates are not monotonically increasing")

    ohlc_nulls = df[["open", "high", "low", "close"]].isnull().any(axis=None)
    if ohlc_nulls:
        bad_rows = df[df[["open", "high", "low", "close"]].isnull().any(axis=1)].index.tolist()
        raise ProviderError(f"[{symbol}] NaN values in OHLC at dates: {bad_rows[:5]}")

    if (df["volume"] <= 0).any():
        bad_rows = df[df["volume"] <= 0].index.tolist()
        raise ProviderError(f"[{symbol}] Non-positive volume at dates: {bad_rows[:5]}")

    return df
