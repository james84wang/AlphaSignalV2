"""Tests for finnhub_provider.py — disabled state and mocked HTTP."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.app.data.finnhub_provider import FinnhubProvider
from backend.app.data.provider import ProviderError


def test_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubProvider()
    assert not provider.enabled


def test_raises_on_get_latest_quote_when_disabled(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubProvider()
    with pytest.raises(ProviderError, match="disabled"):
        provider.get_latest_quote("AAPL")


def test_get_daily_bars_always_raises():
    provider = FinnhubProvider()
    with pytest.raises(ProviderError, match="does not support"):
        provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))


def test_is_trading_day_always_raises():
    provider = FinnhubProvider()
    with pytest.raises(ProviderError, match="does not support"):
        provider.is_trading_day(date(2024, 1, 2))


@patch("backend.app.data.finnhub_provider.httpx.Client")
def test_get_latest_quote_happy_path(mock_client_cls, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key_123")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"c": 192.5, "o": 190.0, "h": 194.0, "l": 189.5, "pc": 191.0, "t": 1700000000}
    mock_resp.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    provider = FinnhubProvider()
    quote = provider.get_latest_quote("AAPL")

    assert quote["symbol"] == "AAPL"
    assert quote["price"] == 192.5
    assert quote["source"] == "finnhub"


@patch("backend.app.data.finnhub_provider.httpx.Client")
def test_get_latest_quote_raises_on_zero_price(mock_client_cls, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key_123")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"c": 0}
    mock_resp.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    provider = FinnhubProvider()
    with pytest.raises(ProviderError, match="no current price"):
        provider.get_latest_quote("AAPL")
