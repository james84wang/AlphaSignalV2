"""Finnhub adapter — secondary source for quotes and earnings.

This is a STUB.  It provides get_latest_quote() only; daily bars are NOT
supported (Finnhub's free tier has strict limits on historical OHLCV).

Set FINNHUB_API_KEY in your .env file to enable.  If the key is absent the
provider disables itself cleanly — callers receive a ProviderError with a
helpful message rather than a crash.

Usage:
    from backend.app.data.finnhub_provider import FinnhubProvider
    provider = FinnhubProvider()          # no-op if key absent
    quote = provider.get_latest_quote("AAPL")
"""
from __future__ import annotations

import logging
import os
from datetime import date

import httpx

from .provider import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider(MarketDataProvider):
    """Secondary data adapter for real-time quotes via Finnhub REST API.

    Reads FINNHUB_API_KEY from the environment.  If absent, all methods raise
    ProviderError(disabled=True) so callers can fall back gracefully.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not self._api_key:
            logger.info(
                "FINNHUB_API_KEY not set — FinnhubProvider disabled. "
                "Set it in your .env file to enable Finnhub quotes."
            )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _require_key(self) -> None:
        if not self.enabled:
            raise ProviderError(
                "FinnhubProvider is disabled: FINNHUB_API_KEY is not set. "
                "Register for a free key at https://finnhub.io and add it to your .env file."
            )

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> None:
        # Finnhub free tier doesn't offer reliable historical OHLCV — use yfinance.
        raise ProviderError(
            "FinnhubProvider does not support get_daily_bars. "
            "Use YFinanceProvider for historical OHLCV data."
        )

    def get_latest_quote(self, symbol: str) -> dict:
        """Fetch a real-time quote from Finnhub /quote endpoint."""
        self._require_key()
        url = f"{_BASE_URL}/quote"
        params = {"symbol": symbol, "token": self._api_key}

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"[{symbol}] Finnhub HTTP error: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"[{symbol}] Finnhub unexpected error: {exc}") from exc

        price = data.get("c")  # current price
        if price is None or price == 0:
            raise ProviderError(f"[{symbol}] Finnhub returned no current price: {data}")

        return {
            "symbol": symbol,
            "price": float(price),
            "open": float(data.get("o", 0)),
            "high": float(data.get("h", 0)),
            "low": float(data.get("l", 0)),
            "prev_close": float(data.get("pc", 0)),
            "timestamp": data.get("t"),
            "source": "finnhub",
        }

    def is_trading_day(self, check_date: date) -> bool:
        raise ProviderError(
            "FinnhubProvider does not support is_trading_day. Use YFinanceProvider."
        )
