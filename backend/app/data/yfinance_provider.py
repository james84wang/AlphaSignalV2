"""yfinance-backed MarketDataProvider — primary data source.

yfinance is an unofficial library that scrapes Yahoo Finance.  It may break
without notice.  All failures are caught, logged, and re-raised as ProviderError
so callers can decide whether to fall back or abort.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

from .provider import MarketDataProvider, ProviderError, validate_bars

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (1, 3, 7)  # seconds between up to 3 retries


def _retry(fn, *args, **kwargs):
    """Call *fn* with retries and exponential-ish back-off. Returns result or raises."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + list(_RETRY_DELAYS), start=1):
        if delay:
            logger.debug("Retrying after %ss (attempt %d)…", delay, attempt)
            time.sleep(delay)
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Attempt %d failed: %s", attempt, exc)
    raise ProviderError(f"All retries exhausted. Last error: {last_exc}") from last_exc


class YFinanceProvider(MarketDataProvider):
    """Fetches daily OHLCV data from Yahoo Finance via yfinance.

    Reliability note: yfinance is unofficial.  Known failure modes:
    - Rate-limiting (429) during bulk downloads.
    - Occasional adjusted-close-only responses (no OHLCV).
    - Index corporate-action splits can shift historical prices without warning.
    All are caught and surfaced as ProviderError.
    """

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for *symbol* between *start* and *end* inclusive."""
        logger.info("Fetching %s bars %s → %s via yfinance", symbol, start, end)

        # yfinance end date is exclusive, so add 1 day.
        end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)

        def _fetch():
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=str(start),
                end=str(end_exclusive.date()),
                interval="1d",
                auto_adjust=True,
                actions=False,
            )
            return df

        try:
            raw = _retry(_fetch)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"[{symbol}] yfinance fetch failed: {exc}") from exc

        if raw is None or raw.empty:
            logger.warning("[%s] yfinance returned empty DataFrame for %s–%s", symbol, start, end)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # Normalise column names (yfinance uses Title Case).
        raw.columns = [c.lower() for c in raw.columns]

        # Keep only the columns we need.
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in raw.columns]
        df = raw[keep].copy()

        # Strip timezone from index (we work with tz-naive dates internally).
        df.index = pd.DatetimeIndex(df.index).tz_localize(None)
        df.index.name = "date"

        # Cast volume to int64 (yfinance sometimes returns float).
        if "volume" in df.columns:
            df["volume"] = df["volume"].astype("int64")

        try:
            df = validate_bars(df, symbol)
        except ProviderError as exc:
            logger.error("Validation failed for %s: %s", symbol, exc)
            raise

        logger.info("[%s] Fetched %d bars", symbol, len(df))
        return df

    def get_latest_quote(self, symbol: str) -> dict:
        """Return the most recent price and timestamp from yfinance fast_info."""
        logger.info("Fetching latest quote for %s", symbol)

        def _fetch():
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = getattr(info, "last_price", None)
            if price is None:
                raise ProviderError(f"[{symbol}] fast_info returned no price")
            return {
                "symbol": symbol,
                "price": float(price),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }

        try:
            return _retry(_fetch)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"[{symbol}] Quote fetch failed: {exc}") from exc

    def is_trading_day(self, check_date: date) -> bool:
        """Return True when *check_date* is a US market trading day.

        Strategy: attempt to fetch 1 bar for SPY on that date.  If we get data,
        it was a trading day.  This is slow — callers should cache results.
        """
        try:
            df = self.get_daily_bars("SPY", check_date, check_date)
            return not df.empty
        except ProviderError:
            return False
