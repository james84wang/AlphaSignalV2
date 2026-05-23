"""Tests for universe.py — watchlist loading and S&P 500/400/600/1000 cache."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from backend.app.data.universe import Universe, fetch_sp500_symbols, fetch_sp400_symbols, fetch_sp600_symbols, fetch_sp1000_symbols


def test_universe_with_watchlist_only(tmp_path):
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("symbol,exchange\nAAPL,NASDAQ\nMSFT,NASDAQ\n")

    u = Universe(watchlist_path=watchlist, include_sp500=False)
    assert "AAPL" in u.symbols
    assert "MSFT" in u.symbols
    assert len(u.symbols) == 2


def test_universe_deduplicates(tmp_path):
    watchlist = tmp_path / "watchlist.csv"
    # AAPL appears twice — should be de-duplicated.
    watchlist.write_text("symbol,exchange\nAAPL,NASDAQ\nAAPL,NYSE\n")

    u = Universe(watchlist_path=watchlist, include_sp500=False)
    assert u.symbols.count("AAPL") == 1


def test_universe_missing_watchlist_ok(tmp_path):
    u = Universe(watchlist_path=tmp_path / "nonexistent.csv", include_sp500=False)
    assert u.symbols == []


def test_universe_bad_watchlist_column(tmp_path, caplog):
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("ticker,exchange\nAAPL,NASDAQ\n")  # wrong column name

    u = Universe(watchlist_path=watchlist, include_sp500=False)
    assert u.symbols == []
    assert "no 'symbol' column" in caplog.text


def test_create_example_watchlist(tmp_path):
    u = Universe(watchlist_path=tmp_path / "watchlist.csv", include_sp500=False)
    u.create_example_watchlist()

    assert (tmp_path / "watchlist.csv").exists()
    df = pd.read_csv(tmp_path / "watchlist.csv")
    assert "symbol" in df.columns
    assert len(df) == 3


def test_create_example_watchlist_does_not_overwrite(tmp_path):
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("symbol,exchange\nGOOG,NASDAQ\n")

    u = Universe(watchlist_path=watchlist, include_sp500=False)
    u.create_example_watchlist()

    df = pd.read_csv(watchlist)
    assert df.iloc[0]["symbol"] == "GOOG"  # unchanged


def test_reload_refreshes_symbols(tmp_path):
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("symbol,exchange\nAAPL,NASDAQ\n")

    u = Universe(watchlist_path=watchlist, include_sp500=False)
    assert u.symbols == ["AAPL"]

    watchlist.write_text("symbol,exchange\nAAPL,NASDAQ\nTSLA,NASDAQ\n")
    u.reload()
    assert "TSLA" in u.symbols


@patch("backend.app.data.universe.pd.read_html")
def test_fetch_sp500_uses_cache(mock_read_html, tmp_path):
    """Once cached, Wikipedia should not be fetched again."""
    cache_file = tmp_path / "sp500.csv"
    cache_file.write_text("symbol,sector,exchange\nAAPL,Technology,NYSE/NASDAQ\n")

    with patch("backend.app.data.universe._SP500_CACHE", cache_file):
        symbols = fetch_sp500_symbols()

    mock_read_html.assert_not_called()
    assert "AAPL" in symbols


@patch("backend.app.data.universe.pd.read_html")
def test_fetch_sp400_uses_cache(mock_read_html, tmp_path):
    """Once cached, Wikipedia should not be fetched again for SP400."""
    cache_file = tmp_path / "sp400.csv"
    cache_file.write_text("symbol\nROLX\nPOWL\n")

    with patch("backend.app.data.universe._SP400_CACHE", cache_file):
        symbols = fetch_sp400_symbols()

    mock_read_html.assert_not_called()
    assert "ROLX" in symbols


@patch("backend.app.data.universe.pd.read_html")
def test_fetch_sp600_uses_cache(mock_read_html, tmp_path):
    """Once cached, Wikipedia should not be fetched again for SP600."""
    cache_file = tmp_path / "sp600.csv"
    cache_file.write_text("symbol\nABCD\nEFGH\n")

    with patch("backend.app.data.universe._SP600_CACHE", cache_file):
        symbols = fetch_sp600_symbols()

    mock_read_html.assert_not_called()
    assert "ABCD" in symbols


@patch("backend.app.data.universe.pd.read_html")
def test_fetch_sp1000_combines_400_and_600(mock_read_html, tmp_path):
    """SP1000 = SP400 ∪ SP600, de-duplicated."""
    cache_400 = tmp_path / "sp400.csv"
    cache_400.write_text("symbol\nABCD\nEFGH\n")
    cache_600 = tmp_path / "sp600.csv"
    cache_600.write_text("symbol\nEFGH\nIJKL\n")  # EFGH overlaps

    with (
        patch("backend.app.data.universe._SP400_CACHE", cache_400),
        patch("backend.app.data.universe._SP600_CACHE", cache_600),
    ):
        symbols = fetch_sp1000_symbols()

    mock_read_html.assert_not_called()
    assert "ABCD" in symbols
    assert "EFGH" in symbols
    assert "IJKL" in symbols
    assert symbols.count("EFGH") == 1  # de-duplicated


def test_universe_with_extra_symbols(tmp_path):
    """extra_symbols are included and de-duplicated."""
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("symbol,exchange\nAAPL,NASDAQ\n")

    u = Universe(watchlist_path=watchlist, include_sp500=False, extra_symbols=["TSLA", "AAPL"])
    assert "TSLA" in u.symbols
    assert "AAPL" in u.symbols
    assert u.symbols.count("AAPL") == 1
