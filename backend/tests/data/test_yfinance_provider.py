"""Tests for yfinance_provider.py — mocked network, no real calls."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.app.data.provider import ProviderError
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.tests.data.conftest import make_bars


def _make_yf_history(n: int = 5) -> pd.DataFrame:
    """Produce a DataFrame that mimics yfinance ticker.history() output."""
    df = make_bars(n=n)
    # yfinance uses Title Case column names.
    df.columns = [c.capitalize() for c in df.columns]
    # yfinance returns a tz-aware index.
    df.index = df.index.tz_localize("America/New_York")
    return df


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_get_daily_bars_happy_path(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _make_yf_history(5)
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    df = provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None  # tz stripped


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_get_daily_bars_empty_response(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    df = provider.get_daily_bars("FAKE", date(2024, 1, 2), date(2024, 1, 8))
    assert df.empty


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_get_daily_bars_raises_on_network_error(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = ConnectionError("timeout")
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_get_latest_quote_happy_path(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.fast_info.last_price = 192.5
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    quote = provider.get_latest_quote("AAPL")

    assert quote["symbol"] == "AAPL"
    assert quote["price"] == 192.5
    assert "timestamp" in quote


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_get_latest_quote_raises_when_no_price(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.fast_info.last_price = None
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_latest_quote("AAPL")


@patch("backend.app.data.yfinance_provider.yf.Ticker")
def test_validation_error_propagated(mock_ticker_cls):
    """If yfinance returns NaN in OHLC, validate_bars raises and it propagates."""
    mock_ticker = MagicMock()
    bad_df = _make_yf_history(5)
    bad_df.loc[bad_df.index[0], "Close"] = float("nan")
    mock_ticker.history.return_value = bad_df
    mock_ticker_cls.return_value = mock_ticker

    provider = YFinanceProvider()
    with pytest.raises(ProviderError, match="NaN"):
        provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))
